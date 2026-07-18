"""Golden dataset evaluation against uploaded Sber debit-card statement (DB).

Runs deterministic insight tools + analytics against the real case_file_transactions
rows. Does not call the LLM — this scores the data plane / analytics correctness.
"""
from __future__ import annotations

import json
import re
from collections import Counter
from decimal import Decimal
from pathlib import Path
from typing import Any, Dict, List, Optional

from app.models.case_file_transaction import CaseFileTransaction
from app.services.chat.statement_insight_tools import (
    category_breakdown,
    counterparty_profile,
    detect_anomalies,
    monthly_breakdown,
    statement_overview,
    suspicion_period_analysis,
)
from app.services.chat.statement_table_session import (
    StatementTableSession,
    bind_statement_table_session,
)
from app.services.chat.statement_table_tools import probe_description
from app.services.transaction_amount_sign import effective_amount_rub
from app.utils.database import SessionLocal

CASE_ID = "ddbdb101-9c46-4aba-9bbe-317531d05e28"
FILE_ID = "06857e7d-d710-4e13-944c-1e9144636533"
FILE_LABEL = "Выписка по счёту дебетовой карты.pdf"

GOLD = {
    "inflow": Decimal("2511563.84"),
    "outflow": Decimal("2522550.36"),
    "op_count_db": 2237,
    "op_count_pdf_approx": 2209,
    "wildberries_mentions": 24,
    "autoplatezh_min": 50,
    "anastasia_min": 50,
}


def parse_money(s: str) -> Optional[Decimal]:
    if not s:
        return None
    text = str(s).replace("\u00a0", " ").replace("\u202f", " ")
    m = re.search(r"([+\-]?\d[\d\s]*)([.,]\d{2})", text)
    if not m:
        return None
    num = m.group(1).replace(" ", "") + m.group(2).replace(",", ".")
    try:
        return Decimal(num)
    except Exception:
        return None


def close(a: Decimal, b: Decimal, tol: Decimal) -> bool:
    return abs(a - b) <= tol


def main() -> None:
    results: List[Dict[str, Any]] = []

    def rec(cid: str, question: str, status: str, detail: str, tools: Optional[List[str]] = None) -> None:
        results.append(
            {
                "id": cid,
                "question": question,
                "status": status,
                "detail": detail,
                "tools": tools or [],
            }
        )
        mark = {"PASS": "PASS", "FAIL": "FAIL", "WARN": "WARN"}[status]
        print(f"[{mark}] {cid}: {detail}")

    db = SessionLocal()
    rows = (
        db.query(CaseFileTransaction)
        .filter(
            CaseFileTransaction.case_id == CASE_ID,
            CaseFileTransaction.file_id == FILE_ID,
        )
        .order_by(CaseFileTransaction.global_row_index.asc())
        .all()
    )
    print(f"Loaded {len(rows)} rows")

    neg = sum(1 for r in rows if r.amount_rub is not None and r.amount_rub < 0)
    pos = sum(1 for r in rows if r.amount_rub is not None and r.amount_rub > 0)
    if neg == 0 and pos > 0:
        rec(
            "DATA",
            "sign health",
            "WARN",
            f"Legacy unsigned DB: pos={pos} neg={neg}; recovery via effective_amount_rub",
        )
    else:
        rec("DATA", "sign health", "PASS", f"pos={pos} neg={neg}")

    session = StatementTableSession(
        case_id=CASE_ID,
        file_id=FILE_ID,
        file_label=FILE_LABEL,
        question="golden-eval",
        rows=rows,
    )

    with bind_statement_table_session(session):
        ov = json.loads(statement_overview.invoke({}))
        cnt = int(ov.get("operation_count") or 0)
        inflow = parse_money(ov.get("inflow_sum", ""))
        outflow = parse_money(ov.get("outflow_sum", ""))
        in_c = int(ov.get("inflow_count") or 0)
        out_c = int(ov.get("outflow_count") or 0)
        net = parse_money(ov.get("net_sum", ""))

        if abs(cnt - GOLD["op_count_db"]) <= 2:
            rec("S1", "Сколько всего операций?", "PASS", f"count={cnt}", ["statement_overview"])
        else:
            rec("S1", "Сколько всего операций?", "FAIL", f"count={cnt}", ["statement_overview"])

        if inflow is not None and close(inflow, GOLD["inflow"], Decimal("5")):
            rec(
                "S2",
                "Сумма поступлений",
                "PASS",
                f"{inflow} (gold {GOLD['inflow']}), n={in_c}",
                ["statement_overview"],
            )
        else:
            rec(
                "S2",
                "Сумма поступлений",
                "FAIL",
                f"got {inflow} gold {GOLD['inflow']}",
                ["statement_overview"],
            )

        if outflow is not None and close(outflow, GOLD["outflow"], Decimal("5")):
            rec(
                "S3",
                "Сумма списаний",
                "PASS",
                f"{outflow} (gold {GOLD['outflow']}), n={out_c}",
                ["statement_overview"],
            )
        elif outflow is not None and close(outflow, GOLD["outflow"], Decimal("3000")):
            rec(
                "S3",
                "Сумма списаний",
                "WARN",
                f"{outflow} ~ gold {GOLD['outflow']} (recovery drift)",
                ["statement_overview"],
            )
        else:
            rec(
                "S3",
                "Сумма списаний",
                "FAIL",
                f"got {outflow} gold {GOLD['outflow']}",
                ["statement_overview"],
            )

        if out_c == 0 and in_c == cnt:
            rec("S3b", "Не все как поступления", "FAIL", f"in={in_c} out={out_c}")
        else:
            rec("S3b", "Не все как поступления", "PASS", f"in={in_c} out={out_c}")

        hits = [
            r
            for r in rows
            if r.operation_datetime_text
            and "10.07.2026" in str(r.operation_datetime_text)
            and "19:28" in str(r.operation_datetime_text)
        ]
        if hits:
            h = hits[0]
            eff = effective_amount_rub(
                h.amount_rub, amount_raw=h.amount_raw, flow_direction=h.flow_direction
            )
            if eff is not None and eff == Decimal("-8000.00"):
                rec(
                    "S4",
                    "10.07.2026 19:28",
                    "PASS",
                    f"eff={eff}; {(h.description or '')[:90]}",
                )
            else:
                rec(
                    "S4",
                    "10.07.2026 19:28",
                    "FAIL",
                    f"eff={eff} stored={h.amount_rub} raw={h.amount_raw!r}",
                )
        else:
            rec("S4", "10.07.2026 19:28", "FAIL", "row not found")

        an = json.loads(detect_anomalies.invoke({}))
        findings = an.get("findings") or []
        cash_codes = [f for f in findings if f.get("code") == "large_cash_out"]
        cash_rows = [
            r
            for r in rows
            if re.search(
                r"банкомат|снят\w*\s*налич|выдача\s*налич",
                str(r.description or ""),
                re.I,
            )
        ]
        if not cash_rows and not cash_codes:
            rec(
                "S5",
                "Наличные/банкомат",
                "PASS",
                "0 cash markers; no large_cash_out",
                ["detect_anomalies"],
            )
        else:
            rec(
                "S5",
                "Наличные/банкомат",
                "WARN",
                f"cash_rows={len(cash_rows)} findings={[c.get('code') for c in cash_codes]}",
                ["detect_anomalies"],
            )

        wb = [
            r
            for r in rows
            if "WILDBERRIES" in str(r.description or "").upper()
            or "WILDBERRIES" in str(r.row_columns or "").upper()
        ]
        if len(wb) >= 15:
            rec("S6", "Wildberries", "PASS", f"rows={len(wb)}")
        else:
            rec("S6", "Wildberries", "FAIL", f"rows={len(wb)}")

        cat = json.loads(category_breakdown.invoke({}))
        cats = cat.get("categories") or []
        outs = [parse_money(c.get("outflow_sum", "")) or Decimal(0) for c in cats]
        labels = " | ".join(f"{c.get('label')}({c.get('op_count')})" for c in cats[:5])
        if cats and any(o > 0 for o in outs):
            rec("S7", "Топ категорий", "PASS", labels[:220], ["category_breakdown"])
        else:
            rec("S7", "Топ категорий", "FAIL", labels[:220], ["category_breakdown"])

        if inflow and outflow and net is not None and out_c > 0:
            rec(
                "M1",
                "Обзор выписки",
                "PASS",
                f"in={inflow} out={outflow} net={net}",
                ["statement_overview"],
            )
        else:
            rec("M1", "Обзор выписки", "FAIL", "broken overview")

        # M2 is category already
        rec(
            "M2",
            "Разбивка по категориям",
            "PASS" if cats and any(o > 0 for o in outs) else "FAIL",
            f"n_cats={len(cats)}",
            ["category_breakdown"],
        )

        cp = json.loads(counterparty_profile.invoke({"token": "AUTOPLATEZH"}))
        if cp.get("matched") and int(cp.get("op_count") or 0) >= GOLD["autoplatezh_min"]:
            rec(
                "M3",
                "AUTOPLATEZH/P2P",
                "PASS",
                f"ops={cp.get('op_count')}",
                ["counterparty_profile"],
            )
        else:
            rec("M3", "AUTOPLATEZH/P2P", "FAIL", str(cp)[:200], ["counterparty_profile"])

        cp2 = json.loads(counterparty_profile.invoke({"token": "Анастасия"}))
        ops_a = int(cp2.get("op_count") or 0)
        if cp2.get("matched") and ops_a >= GOLD["anastasia_min"]:
            rec(
                "M4",
                "Анастасия",
                "PASS",
                f"ops={ops_a} out={cp2.get('outflow_sum')}",
                ["counterparty_profile"],
            )
        elif ops_a > 0:
            rec("M4", "Анастасия", "WARN", f"ops={ops_a}", ["counterparty_profile"])
        else:
            rec("M4", "Анастасия", "FAIL", str(cp2)[:200], ["counterparty_profile"])

        cp3 = json.loads(counterparty_profile.invoke({"token": "TБанк"}))
        if not cp3.get("matched"):
            cp3 = json.loads(counterparty_profile.invoke({"token": "TBank"}))
        if cp3.get("matched") and int(cp3.get("op_count") or 0) >= 1:
            rec(
                "M5",
                "TБанк",
                "PASS",
                f"ops={cp3.get('op_count')}",
                ["counterparty_profile"],
            )
        else:
            rec("M5", "TБанк", "FAIL", str(cp3)[:200], ["counterparty_profile"])

        mb = json.loads(
            monthly_breakdown.invoke({"date_from": "01.01.2026", "date_to": "11.07.2026"})
        )
        months = mb.get("months") or []
        if len(months) >= 5:
            rec(
                "M6",
                "Помесячно 2026",
                "PASS",
                f"months={len(months)}",
                ["monthly_breakdown"],
            )
        else:
            rec("M6", "Помесячно 2026", "FAIL", f"months={len(months)}", ["monthly_breakdown"])

        # Hard multi-step
        findings2 = findings
        codes = [f.get("code") for f in findings2]
        if ov.get("ok") and cat.get("ok") and out_c > 0:
            rec(
                "H1",
                "Многошаговый разбор",
                "PASS",
                f"tools chained; findings={codes}",
                ["statement_overview", "detect_anomalies", "category_breakdown"],
            )
        else:
            rec("H1", "Многошаговый разбор", "FAIL", "pipeline incomplete")

        transit = [f for f in findings2 if f.get("code") == "transit"]
        day = [
            r
            for r in rows
            if r.operation_datetime_text and "10.07.2026" in str(r.operation_datetime_text)
        ]
        day_eff = [
            effective_amount_rub(r.amount_rub, amount_raw=r.amount_raw, flow_direction=r.flow_direction)
            for r in day
        ]
        has_pair = any(a and a >= 8000 for a in day_eff) and any(
            a and a <= -8000 for a in day_eff
        )
        if transit:
            rec(
                "H2",
                "Транзит",
                "PASS",
                f"{transit[0].get('title')}; day_pair={has_pair}",
                ["detect_anomalies"],
            )
        elif has_pair:
            rec(
                "H2",
                "Транзит",
                "WARN",
                "pair +8000/-8000 on 10.07 exists; heuristic did not fire",
                ["detect_anomalies"],
            )
        else:
            rec("H2", "Транзит", "FAIL", "no finding / no pair", ["detect_anomalies"])

        recurring = [f for f in findings2 if f.get("code") == "recurring_transfer"]
        structuring = [f for f in findings2 if f.get("code") == "structuring"]
        if recurring or structuring or ops_a >= 50:
            rec(
                "H3",
                "Систематические переводы",
                "PASS",
                f"recurring={bool(recurring)} structuring={bool(structuring)} anastasia={ops_a}",
                ["detect_anomalies"],
            )
        else:
            rec("H3", "Систематические переводы", "FAIL", "none", ["detect_anomalies"])

        sus = json.loads(suspicion_period_analysis.invoke({"petition_date": "11.07.2026"}))
        windows = sus.get("windows") or []
        bases = [w.get("basis") for w in windows]
        if sus.get("ok") and bases == [
            "preference_1m",
            "preference_6m",
            "unequal_1y",
            "harm_3y",
        ]:
            one = next(w for w in windows if w["basis"] == "preference_1m")
            rec(
                "H4",
                "Периоды подозрительности",
                "PASS",
                f"1m ops={one.get('operation_count')} out={one.get('outflow_sum')}",
                ["suspicion_period_analysis"],
            )
        else:
            rec("H4", "Периоды подозрительности", "FAIL", str(sus)[:250])

        probe = json.loads(probe_description.invoke({"token": "Супермаркеты"}))
        if cats and any(o > 0 for o in outs):
            rec(
                "H5",
                "Супермаркеты vs переводы",
                "PASS",
                f"categories ok; probe_keys={list(probe)[:6]}",
                ["category_breakdown", "probe_description"],
            )
        else:
            rec("H5", "Супермаркеты vs переводы", "FAIL", "weak categories")

        an3 = json.loads(
            detect_anomalies.invoke({"date_from": "11.05.2026", "date_to": "11.07.2026"})
        )
        ov3 = json.loads(
            statement_overview.invoke({"date_from": "11.05.2026", "date_to": "11.07.2026"})
        )
        if an3.get("ok") and int(ov3.get("operation_count") or 0) > 0:
            rec(
                "H6",
                "Опасные за ~2 месяца",
                "PASS",
                f"ops={ov3.get('operation_count')} findings={[f.get('code') for f in (an3.get('findings') or [])]}",
                ["detect_anomalies", "statement_overview"],
            )
        else:
            rec("H6", "Опасные за ~2 месяца", "FAIL", str(an3)[:200])

        cpz = json.loads(counterparty_profile.invoke({"token": "Газпром"}))
        if not cpz.get("matched") or int(cpz.get("op_count") or 0) == 0:
            rec("N1", "Газпром", "PASS", "not found")
        else:
            rec("N1", "Газпром", "FAIL", f"unexpected {cpz.get('op_count')}")

        rec(
            "N3",
            "Не всё как приход",
            "PASS" if out_c > 0 else "FAIL",
            f"out_c={out_c}",
        )

        ov_empty = json.loads(
            statement_overview.invoke({"date_from": "12.05.2019", "date_to": "13.05.2019"})
        )
        if not ov_empty.get("ok") or int(ov_empty.get("operation_count") or 0) == 0:
            rec(
                "N4",
                "Вне периода 2019",
                "PASS",
                ov_empty.get("reason") or f"ops={ov_empty.get('operation_count')}",
            )
        else:
            rec("N4", "Вне периода 2019", "FAIL", f"ops={ov_empty.get('operation_count')}")

    db.close()

    scored = [r for r in results if r["id"] != "DATA"]
    c = Counter(r["status"] for r in scored)
    print("\n========== SUMMARY ==========")
    print(f"PASS={c['PASS']} WARN={c['WARN']} FAIL={c['FAIL']}")
    data = next((r for r in results if r["id"] == "DATA"), None)
    if data:
        print(f"DATA: {data['status']} — {data['detail']}")
    for prefix, name in [
        ("S", "Simple"),
        ("M", "Medium"),
        ("H", "Hard"),
        ("N", "Negative"),
    ]:
        group = [r for r in scored if r["id"].startswith(prefix)]
        p = sum(1 for r in group if r["status"] == "PASS")
        w = sum(1 for r in group if r["status"] == "WARN")
        f = sum(1 for r in group if r["status"] == "FAIL")
        print(f"  {name}: {p} pass / {w} warn / {f} fail (n={len(group)})")

    out_path = Path(__file__).resolve().parent / "golden_statement_eval_report.json"
    out_path.write_text(
        json.dumps(
            {
                "file_id": FILE_ID,
                "case_id": CASE_ID,
                "row_count": len(rows),
                "gold": {k: str(v) for k, v in GOLD.items()},
                "results": results,
                "counts": dict(c),
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    print(f"\nReport written: {out_path}")


if __name__ == "__main__":
    main()

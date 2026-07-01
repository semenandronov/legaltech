"""
Structural SQL metric dimension detection for follow-up turns.

Detects requested aggregate dimension (count vs sum) from word stems —
not full-question templates or routing phrase lists.
"""
from __future__ import annotations

import re
from typing import Literal

SqlMetricDimension = Literal["inherit", "count", "sum"]

_SUM_STEM_RE = re.compile(
    r"\b(?:сумм|итог|оборот|стоим|денег|руб)\w*",
    re.IGNORECASE,
)
_COUNT_STEM_RE = re.compile(
    r"\b(?:колич|скольк|числ|операц)\w*",
    re.IGNORECASE,
)


def resolve_sql_metric_dimension(question: str) -> SqlMetricDimension:
    q = (question or "").strip()
    if not q:
        return "inherit"
    if _SUM_STEM_RE.search(q):
        return "sum"
    if _COUNT_STEM_RE.search(q):
        return "count"
    return "inherit"

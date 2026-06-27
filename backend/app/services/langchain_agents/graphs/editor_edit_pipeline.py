"""
Editor edit pipeline — deterministic validation and compact LLM context.

Product contract:
- Server proposes structured_edits; TipTap on the client applies patches.
- Edit scope (how many locations to change) is planned explicitly before edits.
- No server-side HTML mutation for normal edits.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Sequence, Tuple

from app.config import config as app_config

MAX_EDIT_GENERATION_ATTEMPTS = 2
MAX_EDIT_PLAN_ATTEMPTS = 2
MAX_EDIT_TARGETS_PER_TURN = 25

_BLOCK_HTML_RE = re.compile(
    r"<(p|h[1-6]|li|td|th)([^>]*\sid=[\"']([^\"']+)[\"'][^>]*)>([\s\S]*?)</\1>",
    re.IGNORECASE,
)

_RU_STOPWORDS = frozenset(
    {
        "и", "в", "во", "на", "по", "к", "с", "из", "за", "для", "что", "как",
        "это", "то", "не", "ни", "или", "а", "но", "же", "ли", "бы", "у", "о",
        "об", "от", "до", "при", "над", "под", "мне", "меня", "мой", "моя",
        "мои", "ты", "вы", "мы", "он", "она", "они", "весь", "всю", "все",
        "тот", "та", "те", "этот", "эта", "эти", "где", "когда", "если",
        "чтобы", "только", "ещё", "еще", "уже", "так", "там", "тут", "здесь",
        "пожалуйста", "нужно", "надо", "можно", "сделай", "сделать", "поменяй",
        "замени", "измени", "исправь", "добавь", "убери", "вставь", "удали",
    }
)

_CASE_CONTEXT_SIGNALS = (
    "дело",
    "документ",
    "договор",
    "из файла",
    "из материал",
    "материал",
    "по делу",
    "вложен",
    "прилож",
    "кредитор",
    "должник",
    "инн",
    "огрн",
    "ефрсб",
    "сро",
    "из заявлен",
    "из решен",
    "найди в",
    "возьми из",
    "по договор",
    "из дела",
    "из прилож",
    "справк",
    "выписк",
)


@dataclass(frozen=True)
class DeterministicValidationResult:
    """Outcome of server-side edit checks (no LLM)."""

    is_valid: bool
    errors: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
    enriched_edits: List[Dict[str, Any]] = field(default_factory=list)


_BROADER_DOCUMENT_SIGNALS = (
    "просительн",
    "пункт",
    "подпункт",
    "раздел",
    "шапк",
    "преамбул",
    "таблиц",
    "абзац",
    "в части",
    "в разделе",
    "по документ",
    "в заявлен",
    "в договор",
    "приложен",
    "реквизит",
    "оглавлен",
)

_MULTI_LOCATION_SIGNALS = (
    "везде",
    "все ",
    "всех",
    "кажд",
    "остальн",
    "других мест",
    "другие места",
    "по документ",
    "во всём",
    "во всем",
    "согласован",
    "соответств",
    "привед",
    "унифиц",
    "единобраз",
    "несоответств",
)


@dataclass(frozen=True)
class EditPlanCompleteness:
    """Whether generated edits cover the declared scope plan."""

    is_complete: bool
    expected_targets: int
    actual_edits: int
    issues: List[str] = field(default_factory=list)


def instruction_targets_broader_document(question: str) -> bool:
    q = (question or "").strip().lower()
    if not q:
        return False
    return any(signal in q for signal in _BROADER_DOCUMENT_SIGNALS)


def instruction_targets_multiple_locations(question: str) -> bool:
    q = (question or "").strip().lower()
    if not q:
        return False
    return any(signal in q for signal in _MULTI_LOCATION_SIGNALS)


def instruction_is_dialogue_continuation(question: str) -> bool:
    """
    Короткое подтверждение или отсылка к предыдущему ответу ассистента.
    Такие запросы часто подразумевают несколько правок из истории диалога.
    """
    q = (question or "").strip().lower()
    if not q or len(q) > 120:
        return False
    if q in ("да", "ок", "окей", "хорошо", "согласен", "согласна", "давай", "верно"):
        return True
    continuation_markers = (
        q.startswith("да,"),
        q.startswith("да "),
        "сделай так" in q,
        "сделай это" in q,
        "как ты" in q,
        "как вы" in q,
        "как написал" in q,
        "как сказал" in q,
        "исправь это" in q,
        "исправь как" in q,
        "приведи в соответствие" in q,
        "приведи к" in q,
    )
    return any(continuation_markers)


def requires_broad_document_context(
    question: str,
    *,
    has_dialogue_history: bool,
) -> bool:
    """Whether generate_edits needs wide document context (not compact snippets only)."""
    if instruction_targets_broader_document(question):
        return True
    if instruction_targets_multiple_locations(question):
        return True
    if has_dialogue_history and instruction_is_dialogue_continuation(question):
        return True
    return False


def editor_needs_case_context(
    question: str,
    *,
    editor_mode_hint: Optional[str] = None,
    attached_file_ids: Optional[Sequence[str]] = None,
    selected_text: Optional[str] = None,
) -> bool:
    """
    Whether editor_enrich should run case RAG for this turn.

    Edit mode skips RAG unless the user explicitly needs case materials.
    Ask/Draft keep RAG when a case is attached (question may reference files).
    """
    if attached_file_ids:
        return True

    hint = (editor_mode_hint or "").strip().lower()
    if hint != "edit":
        return True

    q = (question or "").strip().lower()
    if not q and (selected_text or "").strip():
        return False

    return any(signal in q for signal in _CASE_CONTEXT_SIGNALS)


def _question_tokens(question: str) -> List[str]:
    raw = re.findall(r"[a-zA-Zа-яА-ЯёЁ0-9]+", (question or "").lower())
    return [t for t in raw if len(t) >= 3 and t not in _RU_STOPWORDS]


def _score_outline_blocks(
    outline: List[Dict[str, Any]],
    question: str,
    *,
    extra_search_text: str = "",
) -> List[Tuple[int, str]]:
    tokens = _question_tokens(f"{question} {extra_search_text}")
    if not tokens:
        return []
    scored: List[Tuple[int, str]] = []
    for block in outline:
        node_id = str(block.get("node_id") or "")
        text = str(block.get("text") or "").lower()
        if not node_id:
            continue
        score = sum(1 for tok in tokens if tok in text)
        if score > 0:
            scored.append((score, node_id))
    scored.sort(key=lambda x: (-x[0], x[1]))
    return scored


def _extract_block_html(document_html: str, node_id: str) -> Optional[str]:
    if not node_id or not document_html:
        return None
    pattern = re.compile(
        rf"<(p|h[1-6]|li|td|th)([^>]*\sid=[\"']{re.escape(node_id)}[\"'][^>]*)>[\s\S]*?</\1>",
        re.IGNORECASE,
    )
    match = pattern.search(document_html)
    return match.group(0) if match else None


def build_generate_edits_document_section(
    document_html: str,
    question: str,
    *,
    outline: Optional[List[Dict[str, Any]]] = None,
    broad_context: bool = False,
    extra_search_text: str = "",
) -> str:
    """
    Compact document section for generate_edits LLM prompt.

    Small documents: full HTML. Large documents: outline + HTML of relevant blocks.
    broad_context: include more blocks (multi-location edits, dialogue continuations).
    """
    html = (document_html or "").strip()
    if not html:
        return ""

    full_threshold = max(
        4000,
        int(getattr(app_config, "EDITOR_GENERATE_EDITS_FULL_HTML_THRESHOLD", 12000) or 12000),
    )
    broad_threshold = max(full_threshold, full_threshold * 2)
    if len(html) <= full_threshold or (broad_context and len(html) <= broad_threshold):
        return html

    blocks = outline if outline is not None else _build_outline_from_html(html)
    if not blocks:
        cap = max(4000, int(getattr(app_config, "EDITOR_GENERATE_EDITS_FALLBACK_HTML_CHARS", 16000) or 16000))
        return html[:cap] + f"\n<!-- truncated: first {cap} of {len(html)} chars -->"

    default_limit = max(
        3,
        int(getattr(app_config, "EDITOR_GENERATE_EDITS_RELEVANT_BLOCK_LIMIT", 8) or 8),
    )
    broad_limit = max(
        default_limit,
        int(getattr(app_config, "EDITOR_GENERATE_EDITS_BROAD_BLOCK_LIMIT", 24) or 24),
    )
    block_limit = min(len(blocks), broad_limit if broad_context else default_limit)

    scored = _score_outline_blocks(blocks, question, extra_search_text=extra_search_text)
    chosen_ids = [node_id for _, node_id in scored[:block_limit]]

    if not chosen_ids and blocks:
        chosen_ids = [str(b.get("node_id")) for b in blocks[:block_limit] if b.get("node_id")]

    snippets: List[str] = []
    used_chars = 0
    max_snippet_chars = max(
        8000,
        int(getattr(app_config, "EDITOR_GENERATE_EDITS_BLOCK_SNIPPETS_MAX_CHARS", 20000) or 20000),
    )
    for node_id in chosen_ids:
        snippet = _extract_block_html(html, node_id)
        if not snippet:
            continue
        if used_chars + len(snippet) > max_snippet_chars:
            break
        snippets.append(snippet)
        used_chars += len(snippet)

    parts = [
        f"<!-- compact context: {len(html)} chars total; "
        f"{len(snippets)} block(s) with full HTML; use OUTLINE node_id for other blocks -->",
    ]
    if snippets:
        parts.append("РЕЛЕВАНТНЫЕ БЛОКИ (полный HTML):")
        parts.extend(snippets)
    else:
        head = max(4000, full_threshold // 2)
        parts.append(f"ФРАГМЕНТ ДОКУМЕНТА (начало):\n{html[:head]}")
    return "\n\n".join(parts)


def _build_outline_from_html(html: str, max_blocks: int = 200, preview_len: int = 200) -> List[Dict[str, Any]]:
    import html as html_module

    outline: List[Dict[str, Any]] = []
    for match in _BLOCK_HTML_RE.finditer(html):
        tag = match.group(1).lower()
        node_id = match.group(3)
        inner = re.sub(r"<[^>]+>", "", match.group(4) or "")
        inner = html_module.unescape(re.sub(r"\s+", " ", inner)).strip()
        outline.append(
            {
                "node_id": node_id,
                "type": tag,
                "text": inner[:preview_len] + ("…" if len(inner) > preview_len else ""),
            }
        )
        if len(outline) >= max_blocks:
            break
    return outline


def normalize_edit_scope(scope: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    """Normalize scope dict from LLM or state."""
    if not scope or not isinstance(scope, dict):
        return {"target_count": 0, "targets": []}
    targets = scope.get("targets") or []
    if not isinstance(targets, list):
        targets = []
    target_count = scope.get("target_count")
    if not isinstance(target_count, int) or target_count < 1:
        target_count = len(targets) if targets else 0
    return {"target_count": target_count, "targets": targets}


def check_edit_plan_completeness(
    edit_scope: Optional[Dict[str, Any]],
    structured_edits: Sequence[Dict[str, Any]],
) -> EditPlanCompleteness:
    """
    Verify that structured_edits cover every target in the declared scope plan.
    """
    scope = normalize_edit_scope(edit_scope)
    targets = scope["targets"]
    if not targets:
        actual = len(structured_edits or [])
        return EditPlanCompleteness(
            is_complete=actual > 0,
            expected_targets=1 if actual > 0 else 0,
            actual_edits=actual,
            issues=[] if actual > 0 else ["Нет правок в ответе модели"],
        )

    expected = max(scope["target_count"], len(targets))
    actual = len(structured_edits or [])
    issues: List[str] = []

    if actual < expected:
        issues.append(
            f"План охватывает {expected} мест, сгенерировано {actual} правок"
        )

    planned_ids = {
        str(t.get("node_id"))
        for t in targets
        if isinstance(t, dict) and t.get("node_id")
    }
    edit_ids = {
        str(e.get("node_id"))
        for e in structured_edits
        if isinstance(e, dict) and e.get("node_id")
    }
    missing_ids = planned_ids - edit_ids
    if missing_ids:
        issues.append(
            "Нет правок для блоков: " + ", ".join(sorted(missing_ids))
        )

    return EditPlanCompleteness(
        is_complete=len(issues) == 0,
        expected_targets=expected,
        actual_edits=actual,
        issues=issues,
    )


def build_edit_generation_retry_hint(completeness: EditPlanCompleteness) -> str:
    """Human-readable correction block for a second LLM attempt."""
    lines = [
        "ПРЕДЫДУЩИЙ ОТВЕТ НЕПОЛНЫЙ — дополните список edits.",
        f"Ожидалось целей: {completeness.expected_targets}, получено правок: {completeness.actual_edits}.",
    ]
    lines.extend(f"- {issue}" for issue in completeness.issues)
    lines.append(
        "Верни полный scope.targets и edits: по одной правке на КАЖДУЮ цель из плана."
    )
    return "\n".join(lines)


def enrich_structured_edits(
    structured_edits: List[Dict[str, Any]],
    document_context: str,
    *,
    node_id_in_document,
    extract_block_text_by_node_id,
) -> List[Dict[str, Any]]:
    """Fill found_in_document flags and block original_text without LLM."""
    enriched: List[Dict[str, Any]] = []
    for edit in structured_edits:
        if not isinstance(edit, dict):
            continue
        row = dict(edit)
        node_id = row.get("node_id")
        original_text = (row.get("original_text") or "").strip()

        if node_id:
            if not original_text:
                row["original_text"] = extract_block_text_by_node_id(document_context, node_id)
            row["found_in_document"] = node_id_in_document(node_id, document_context)
        elif original_text:
            row["found_in_document"] = original_text in document_context

        enriched.append(row)
    return enriched


def validate_structured_edits_deterministic(
    structured_edits: List[Dict[str, Any]],
    document_context: str,
    *,
    node_id_in_document,
    extract_block_text_by_node_id,
    edit_scope: Optional[Dict[str, Any]] = None,
    fail_closed_on_incomplete_scope: bool = True,
) -> DeterministicValidationResult:
    """
    Validate edit proposals deterministically.

    When ``fail_closed_on_incomplete_scope`` is True, incomplete plans are rejected (no partial UI).
    """
    if not structured_edits:
        return DeterministicValidationResult(
            is_valid=True,
            warnings=["Нет правок для проверки"],
            enriched_edits=[],
        )

    enriched = enrich_structured_edits(
        structured_edits,
        document_context,
        node_id_in_document=node_id_in_document,
        extract_block_text_by_node_id=extract_block_text_by_node_id,
    )

    errors: List[str] = []
    warnings: List[str] = []
    seen_node_ids: set[str] = set()

    for idx, edit in enumerate(enriched, start=1):
        node_id = edit.get("node_id")
        original_text = (edit.get("original_text") or "").strip()
        new_text = (edit.get("new_text") or "").strip()

        if not new_text:
            errors.append(f"Правка {idx}: пустой new_text")
            continue

        if node_id:
            if node_id in seen_node_ids:
                warnings.append(f"Правка {idx}: повтор node_id {node_id}")
            seen_node_ids.add(str(node_id))
            if not edit.get("found_in_document"):
                warnings.append(f"Правка {idx}: блок {node_id} не найден в документе")
        elif original_text:
            if not edit.get("found_in_document"):
                warnings.append(
                    f"Правка {idx}: фрагмент не найден в документе "
                    f"({original_text[:40]}…)"
                )
        else:
            errors.append(f"Правка {idx}: нужен node_id или original_text")

    found_count = sum(1 for e in enriched if e.get("found_in_document"))
    if found_count == 0 and enriched:
        warnings.append("Ни одна правка не сопоставлена с документом — проверьте вручную")

    completeness = check_edit_plan_completeness(edit_scope, enriched)
    if not completeness.is_complete:
        warnings.extend(completeness.issues)
        if fail_closed_on_incomplete_scope:
            errors.extend(completeness.issues)
            return DeterministicValidationResult(
                is_valid=False,
                errors=errors,
                warnings=warnings,
                enriched_edits=[],
            )

    is_valid = len(errors) == 0 and bool(enriched)
    return DeterministicValidationResult(
        is_valid=is_valid,
        errors=errors,
        warnings=warnings,
        enriched_edits=enriched,
    )


def format_incomplete_edit_failure_message(
    completeness: EditPlanCompleteness,
    *,
    minimum_targets: Optional[int] = None,
) -> str:
    """User-visible message when edit generation did not meet the plan (fail-closed)."""
    expected = completeness.expected_targets
    if minimum_targets and minimum_targets > expected:
        expected = minimum_targets
    lines = [
        (
            f"Не удалось подготовить все правки: ожидалось {expected}, "
            f"получено {completeness.actual_edits}."
        ),
        "Уточните запрос, перечислите места явно или повторите попытку.",
    ]
    for issue in completeness.issues[:3]:
        lines.append(f"• {issue}")
    return "\n".join(lines)


def format_edit_turn_response(
    structured_edits: Sequence[Dict[str, Any]],
    *,
    waiting_for_approval: bool = False,
    approval_count: int = 0,
) -> str:
    """Short assistant message for edit turns (no follow-up LLM)."""
    if waiting_for_approval:
        return (
            f"Подготовлено {approval_count} правок — это много, нужно подтверждение.\n\n"
            "Напишите «одобряю правки», чтобы показать их в чате, или «отмена»."
        )

    edits = list(structured_edits or [])
    if not edits:
        return "Не удалось подготовить правки. Уточните запрос или выделите фрагмент в документе."

    found = sum(1 for e in edits if e.get("found_in_document"))
    n = len(edits)
    if found == n:
        suffix = "Примите или отклоните каждую в панели правок."
    elif found > 0:
        suffix = (
            f"{found} из {n} сопоставлены с документом автоматически; "
            "остальные может потребоваться вставить вручную."
        )
    else:
        suffix = "Автоматическое сопоставление не удалось — проверьте текст или выделите фрагмент."

    word = "правку" if n == 1 else ("правки" if 2 <= n <= 4 else "правок")
    return f"Предлагаю {n} {word}. {suffix}"

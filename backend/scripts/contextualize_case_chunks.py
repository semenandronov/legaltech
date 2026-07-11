#!/usr/bin/env python3
"""Anthropic-style contextual labels for case chunks + re-embed.

For each chunk: short LLM situating sentence (reasoning OFF) → embedding_text → re-embed.

Usage:
  cd backend && python -m scripts.contextualize_case_chunks \\
    --case-id 0604cbe5-d37d-473f-aa90-d4ad7e7a26fc

Cost uses Yandex Qwen3.5/3.6 35B rates (Polza yandex mirror / YC same as 3.5):
  0.26 ₽ / 1k input, 0.39 ₽ / 1k output (incl. VAT).
"""
from __future__ import annotations

import argparse
import json
import logging
import re
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from dotenv import load_dotenv

BACKEND_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = BACKEND_ROOT.parent
sys.path.insert(0, str(BACKEND_ROOT))

load_dotenv(REPO_ROOT / ".env")
load_dotenv(BACKEND_ROOT / ".env")

from langchain_core.documents import Document
from langchain_core.messages import HumanMessage, SystemMessage
from sqlalchemy import text

from app.services.llm_factory import create_llm, user_facing_llm_reasoning_kwargs
from app.services.pgvector_store import CaseVectorStore
from app.services.yandex_embeddings import YandexEmbeddings

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

DEFAULT_CASE_ID = "0604cbe5-d37d-473f-aa90-d4ad7e7a26fc"
# Yandex Cloud Qwen 3.6 = Qwen 3.5 price; Polza yandex provider: 260/390 ₽ per 1M
RUB_PER_1K_INPUT = 0.26
RUB_PER_1K_OUTPUT = 0.39
EMBED_BATCH = 32

SYSTEM_PROMPT = """Ты размечаешь фрагменты юридических документов для семантического поиска.
Верни ОДНУ короткую фразу (1–2 предложения, до 40 слов) на русском: где этот кусок в документе и о чём он.
Фокус: отличить срок/цену/предмет/стороны/ответственность/просьбу/шапку и т.п.
Не цитируй кусок целиком. Не рассуждай. Только итоговая фраза, без кавычек и префиксов."""


def _usage_from_response(resp: Any) -> Tuple[int, int]:
    um = getattr(resp, "usage_metadata", None) or {}
    if isinstance(um, dict) and (um.get("input_tokens") or um.get("output_tokens")):
        return int(um.get("input_tokens") or 0), int(um.get("output_tokens") or 0)
    meta = getattr(resp, "response_metadata", None) or {}
    raw = meta.get("token_usage") or meta.get("usage") or {}
    if isinstance(raw, dict):
        inn = raw.get("prompt_tokens") or raw.get("input_tokens") or 0
        out = raw.get("completion_tokens") or raw.get("output_tokens") or 0
        return int(inn or 0), int(out or 0)
    return 0, 0


def _clean_label(raw: str) -> str:
    s = (raw or "").strip()
    s = re.sub(r"^```(?:\w+)?\s*|\s*```$", "", s).strip()
    s = re.sub(r"^(контекст|context|ответ|фраза)\s*[:\-—]\s*", "", s, flags=re.I)
    s = re.sub(r"\s+", " ", s).strip(" \"'")
    if len(s) > 320:
        s = s[:317].rstrip() + "…"
    return s


def _breadcrumb(md: Dict[str, Any]) -> str:
    parts: List[str] = []
    for p in md.get("parent_path") or []:
        if isinstance(p, str) and p.strip():
            parts.append(p.strip())
    st = str(md.get("section_title") or "").strip()
    if st and st not in parts:
        parts.append(st)
    return " > ".join(parts)


def _build_embedding_text(page_content: str, label: str, breadcrumb: str) -> str:
    body = page_content or ""
    bits = [b for b in (breadcrumb, label) if b]
    ctx = " | ".join(bits)
    if ctx:
        return f"[Контекст: {ctx}]\n{body}"
    return body


def _load_file_meta(engine, case_id: str) -> Dict[str, Dict[str, str]]:
    out: Dict[str, Dict[str, str]] = {}
    with engine.connect() as conn:
        rows = conn.execute(
            text(
                """
                SELECT id::text, filename,
                       COALESCE(doc_summary_short, ''),
                       COALESCE(doc_type::text, ''),
                       COALESCE(doc_type_label, '')
                FROM files WHERE case_id = :c
                """
            ),
            {"c": case_id},
        ).fetchall()
    for fid, fn, summary, dtype, label in rows:
        out[str(fid)] = {
            "filename": fn or "",
            "summary": (summary or "")[:500],
            "doc_type": dtype or label or "",
        }
    return out


def _load_chunks(engine, case_id: str) -> List[Dict[str, Any]]:
    with engine.connect() as conn:
        rows = conn.execute(
            text(
                """
                SELECT uuid, document->>'page_content' AS pc, document->'metadata' AS meta
                FROM langchain_pg_embedding
                WHERE case_id = :c
                ORDER BY (document->'metadata'->>'source_file') NULLS LAST,
                         (document->'metadata'->>'chunk_index')::int NULLS LAST
                """
            ),
            {"c": case_id},
        ).fetchall()
    items: List[Dict[str, Any]] = []
    for rid, pc, meta_raw in rows:
        meta = json.loads(meta_raw) if isinstance(meta_raw, str) else (meta_raw or {})
        if not isinstance(meta, dict):
            meta = {}
        items.append({"uuid": str(rid), "page_content": pc or "", "metadata": meta})
    return items


def _label_one(
    llm: Any,
    *,
    filename: str,
    summary: str,
    breadcrumb: str,
    chunk: str,
) -> Tuple[str, int, int]:
    user = (
        f"Файл: {filename}\n"
        f"Кратко о документе: {summary or '—'}\n"
        f"Раздел/путь: {breadcrumb or '—'}\n"
        f"Кусок:\n{(chunk or '')[:1800]}\n\n"
        f"Короткая фраза-контекст:"
    )
    resp = llm.invoke(
        [
            SystemMessage(content=SYSTEM_PROMPT),
            HumanMessage(content=user),
        ]
    )
    content = getattr(resp, "content", None)
    if isinstance(content, list):
        content = "".join(
            (p.get("text") if isinstance(p, dict) else str(p)) for p in content
        )
    label = _clean_label(str(content or ""))
    inn, out = _usage_from_response(resp)
    return label, inn, out


def _apply_checkpoint_labels(
    chunks: List[Dict[str, Any]],
    file_meta: Dict[str, Dict[str, str]],
    pairs: List[Dict[str, Any]],
) -> Dict[str, Dict[str, Any]]:
    """Map recovered {chunk,label} pairs onto DB chunks (greedy unique match)."""
    by_chunk: Dict[str, List[str]] = {}
    for p in pairs:
        ch = (p.get("chunk") or "").strip()
        lab = _clean_label(str(p.get("label") or ""))
        if not ch or not lab:
            continue
        by_chunk.setdefault(ch, []).append(lab)
        # also key by truncated prompt body (chunk may be cut at 1800)
        if len(ch) > 50:
            by_chunk.setdefault(ch[:1800].strip(), []).append(lab)

    results: Dict[str, Dict[str, Any]] = {}
    for item in chunks:
        pc = item["page_content"] or ""
        md = item["metadata"]
        crumb = _breadcrumb(md)
        labels = by_chunk.get(pc.strip()) or by_chunk.get(pc[:1800].strip()) or []
        if not labels:
            # fuzzy: longest prefix match among keys
            best = ""
            for key in by_chunk:
                if pc.startswith(key) or key.startswith(pc[:200]):
                    if len(key) > len(best):
                        best = key
            labels = by_chunk.get(best) or []
        if not labels:
            continue
        label = labels.pop(0)
        et = _build_embedding_text(pc, label, crumb)
        results[item["uuid"]] = {
            "contextual_label": label,
            "embedding_text": et,
            "breadcrumb": crumb,
            "input_tokens": 0,
            "output_tokens": 0,
            "metadata": md,
            "page_content": pc,
        }
    return results


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--case-id", default=DEFAULT_CASE_ID)
    ap.add_argument("--workers", type=int, default=6)
    ap.add_argument("--limit", type=int, default=0, help="0 = all chunks")
    ap.add_argument("--dry-run", action="store_true", help="LLM only for first N, no DB write")
    ap.add_argument("--skip-embed", action="store_true", help="Write labels but skip re-embed")
    ap.add_argument(
        "--from-checkpoint",
        type=str,
        default="",
        help="JSON list of {chunk,label} from prior LLM run; skip LLM",
    )
    ap.add_argument(
        "--tokens-in",
        type=int,
        default=0,
        help="Override input token count for cost report (with --from-checkpoint)",
    )
    ap.add_argument(
        "--tokens-out",
        type=int,
        default=0,
        help="Override output token count for cost report (with --from-checkpoint)",
    )
    args = ap.parse_args()

    case_id = args.case_id
    store = CaseVectorStore()
    file_meta = _load_file_meta(store.engine, case_id)
    chunks = _load_chunks(store.engine, case_id)
    if args.limit and args.limit > 0:
        chunks = chunks[: args.limit]

    if not chunks:
        logger.error("No chunks for case %s", case_id)
        return 1

    logger.info(
        "Case %s: %d chunks, %d files. reasoning=disabled workers=%d",
        case_id,
        len(chunks),
        len(file_meta),
        args.workers,
    )

    results: Dict[str, Dict[str, Any]] = {}
    total_in = 0
    total_out = 0
    failures = 0
    t0 = time.time()
    checkpoint_path = BACKEND_ROOT / "evals" / f"case_{case_id[:8]}_contextual_labels_live.json"

    if args.from_checkpoint:
        pairs = json.loads(Path(args.from_checkpoint).read_text(encoding="utf-8"))
        results = _apply_checkpoint_labels(chunks, file_meta, pairs)
        total_in = int(args.tokens_in or 0)
        total_out = int(args.tokens_out or 0)
        failures = max(0, len(chunks) - len(results))
        logger.info(
            "Loaded checkpoint %s → matched %d/%d chunks",
            args.from_checkpoint,
            len(results),
            len(chunks),
        )
    else:
        llm = create_llm(
            temperature=0.0,
            use_rate_limiting=True,
            timeout=60.0,
            max_tokens=120,
            **user_facing_llm_reasoning_kwargs(mode="normal"),
        )

        def work(item: Dict[str, Any]) -> Tuple[str, Dict[str, Any]]:
            md = item["metadata"]
            fid = str(md.get("file_id") or md.get("doc_id") or "")
            fm = file_meta.get(fid) or {}
            filename = (
                fm.get("filename")
                or str(md.get("source_file") or "")
                or "документ"
            )
            summary = fm.get("summary") or ""
            crumb = _breadcrumb(md)
            label, inn, out = _label_one(
                llm,
                filename=filename,
                summary=summary,
                breadcrumb=crumb,
                chunk=item["page_content"],
            )
            if not label:
                raise RuntimeError("empty label")
            et = _build_embedding_text(item["page_content"], label, crumb)
            return item["uuid"], {
                "contextual_label": label,
                "embedding_text": et,
                "breadcrumb": crumb,
                "input_tokens": inn,
                "output_tokens": out,
                "metadata": md,
                "page_content": item["page_content"],
            }

        with ThreadPoolExecutor(max_workers=max(1, args.workers)) as pool:
            futs = {pool.submit(work, it): it["uuid"] for it in chunks}
            done = 0
            for fut in as_completed(futs):
                rid = futs[fut]
                done += 1
                try:
                    uid, payload = fut.result()
                    results[uid] = payload
                    total_in += int(payload["input_tokens"])
                    total_out += int(payload["output_tokens"])
                    if done % 25 == 0 or done == len(chunks):
                        logger.info(
                            "labeled %d/%d  in_tok=%d out_tok=%d",
                            done,
                            len(chunks),
                            total_in,
                            total_out,
                        )
                except Exception as exc:
                    failures += 1
                    logger.error("chunk %s failed: %s", rid, exc)

        # Persist labels so a DB/embed failure does not require re-paying for LLM.
        live = [
            {
                "uuid": uid,
                "chunk": r["page_content"],
                "label": r["contextual_label"],
                "breadcrumb": r.get("breadcrumb") or "",
                "input_tokens": r["input_tokens"],
                "output_tokens": r["output_tokens"],
            }
            for uid, r in results.items()
        ]
        checkpoint_path.write_text(json.dumps(live, ensure_ascii=False), encoding="utf-8")
        logger.info("Checkpoint → %s (%d labels)", checkpoint_path, len(live))

    label_s = time.time() - t0
    llm_cost = total_in / 1000.0 * RUB_PER_1K_INPUT + total_out / 1000.0 * RUB_PER_1K_OUTPUT

    # Fallback token estimate if API omitted usage
    if total_in == 0 and results and not args.from_checkpoint:
        est_in = sum(
            200 + len((r["page_content"] or "")) // 3 + len((r.get("breadcrumb") or "")) // 3
            for r in results.values()
        )
        est_out = sum(max(20, len(r["contextual_label"]) // 3) for r in results.values())
        logger.warning(
            "API usage missing; estimating tokens in≈%d out≈%d", est_in, est_out
        )
        total_in, total_out = est_in, est_out
        llm_cost = total_in / 1000.0 * RUB_PER_1K_INPUT + total_out / 1000.0 * RUB_PER_1K_OUTPUT

    logger.info(
        "LLM done: ok=%d fail=%d in %.1fs | tokens in=%d out=%d | ≈%.2f ₽",
        len(results),
        failures,
        label_s,
        total_in,
        total_out,
        llm_cost,
    )

    if args.dry_run:
        sample = next(iter(results.values()))
        print(json.dumps({
            "dry_run": True,
            "sample_label": sample["contextual_label"],
            "sample_et_prefix": sample["embedding_text"][:240],
            "tokens_in": total_in,
            "tokens_out": total_out,
            "llm_cost_rub": round(llm_cost, 2),
        }, ensure_ascii=False, indent=2))
        return 0 if failures == 0 else 2

    now = datetime.now(timezone.utc).isoformat()
    updated = 0
    with store.engine.begin() as conn:
        for uid, payload in results.items():
            md = dict(payload["metadata"] or {})
            md["embedding_text"] = payload["embedding_text"]
            md["contextual_label"] = payload["contextual_label"]
            md["contextualized_at"] = now
            md["contextualize_model"] = "qwen3.6-35b-a3b"
            doc_json = {
                "page_content": payload["page_content"],
                "metadata": md,
            }
            conn.execute(
                text(
                    """
                    UPDATE langchain_pg_embedding
                    SET document = CAST(:doc AS jsonb)
                    WHERE uuid = :uid AND case_id = :cid
                    """
                ),
                {
                    "doc": json.dumps(doc_json, ensure_ascii=False),
                    "uid": uid,
                    "cid": case_id,
                },
            )
            updated += 1
    logger.info("Wrote contextual metadata for %d chunks", updated)

    embed_cost_note = 0.0
    if not args.skip_embed:
        embedder = YandexEmbeddings()
        texts = [results[uid]["embedding_text"] for uid in results]
        ids = list(results.keys())
        t_emb = time.time()
        for start in range(0, len(texts), EMBED_BATCH):
            batch_t = texts[start : start + EMBED_BATCH]
            batch_ids = ids[start : start + EMBED_BATCH]
            vectors = embedder.embed_documents(batch_t)
            with store.engine.begin() as conn:
                for rid, vec in zip(batch_ids, vectors):
                    conn.execute(
                        text(
                            """
                            UPDATE langchain_pg_embedding
                            SET embedding = CAST(:vec AS vector)
                            WHERE uuid = :uid AND case_id = :cid
                            """
                        ),
                        {
                            "vec": "[" + ",".join(str(float(x)) for x in vec) + "]",
                            "uid": rid,
                            "cid": case_id,
                        },
                    )
            logger.info("embedded %d/%d", min(start + EMBED_BATCH, len(texts)), len(texts))
        # Rough embed cost: Yandex embeddings ~0.01 ₽ / 1k tokens
        emb_chars = sum(len(t) for t in texts)
        emb_tok_est = emb_chars / 3.0
        embed_cost_note = emb_tok_est / 1000.0 * 0.01
        logger.info("Re-embed done in %.1fs (est embed ≈%.2f ₽)", time.time() - t_emb, embed_cost_note)

    report = {
        "case_id": case_id,
        "chunks_total": len(chunks),
        "chunks_labeled": len(results),
        "failures": failures,
        "llm_seconds": round(label_s, 1),
        "tokens_in": total_in,
        "tokens_out": total_out,
        "rate_rub_per_1k": {"input": RUB_PER_1K_INPUT, "output": RUB_PER_1K_OUTPUT},
        "llm_cost_rub": round(llm_cost, 2),
        "embed_cost_rub_est": round(embed_cost_note, 2),
        "total_cost_rub_est": round(llm_cost + embed_cost_note, 2),
        "sample_labels": [
            results[u]["contextual_label"]
            for u in list(results.keys())[:5]
        ],
    }
    out_path = BACKEND_ROOT / "evals" / "case_shak_contextualize_cost.json"
    out_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    logger.info("Report → %s", out_path)
    return 0 if failures == 0 else 2


if __name__ == "__main__":
    raise SystemExit(main())

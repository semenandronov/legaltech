#!/usr/bin/env python3
"""Замер latency и rate-limit Yandex Embeddings (те же ключи/настройки, что в проде)."""
from __future__ import annotations

import logging
import os
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from typing import List, Optional

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv

_backend = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_repo = os.path.dirname(_backend)
load_dotenv(os.path.join(_backend, ".env"))
load_dotenv(os.path.join(_repo, ".env"))

from app.config import config
from app.services.yandex_embeddings import get_yandex_embeddings, warmup_yandex_embeddings

logging.basicConfig(level=logging.WARNING, format="%(levelname)s %(name)s: %(message)s")
logger = logging.getLogger("benchmark_yandex_embeddings")


@dataclass
class BurstResult:
    label: str
    count: int
    wall_sec: float
    ok: int = 0
    errors: List[str] = field(default_factory=list)
    latencies_sec: List[float] = field(default_factory=list)

    @property
    def rps(self) -> float:
        return self.count / self.wall_sec if self.wall_sec > 0 else 0.0

    @property
    def p50(self) -> Optional[float]:
        if not self.latencies_sec:
            return None
        s = sorted(self.latencies_sec)
        return s[len(s) // 2]

    @property
    def p95(self) -> Optional[float]:
        if not self.latencies_sec:
            return None
        s = sorted(self.latencies_sec)
        idx = min(len(s) - 1, int(len(s) * 0.95))
        return s[idx]


def _mask(s: str) -> str:
    if not s or len(s) < 8:
        return "(not set)"
    return s[:4] + "…" + s[-4:]


def _legal_query(i: int) -> str:
    samples = [
        "статья 33 127-ФЗ минимальный размер требований банкротство юридическое лицо",
        "порог возбуждения дела о несостоятельности 2 млн рублей",
        "срок просрочки исполнения обязательств три месяца банкротство",
        "основания возбуждения дела о банкротстве должника",
        "кредитор обращение в арбитражный суд банкротство юрлица",
    ]
    return samples[i % len(samples)]


def _embed_one(text: str) -> tuple[float, Optional[str]]:
    t0 = time.perf_counter()
    try:
        emb = get_yandex_embeddings()
        vec = emb.embed_query(text)
        if not vec or len(vec) != 256:
            return time.perf_counter() - t0, f"bad vector dim={len(vec) if vec else 0}"
        return time.perf_counter() - t0, None
    except Exception as exc:
        return time.perf_counter() - t0, str(exc)


def _run_burst(label: str, count: int, *, parallel: bool) -> BurstResult:
    texts = [_legal_query(i) for i in range(count)]
    result = BurstResult(label=label, count=count, wall_sec=0.0)
    t0 = time.perf_counter()

    if parallel:
        with ThreadPoolExecutor(max_workers=min(count, 50)) as pool:
            futures = {pool.submit(_embed_one, t): i for i, t in enumerate(texts)}
            for fut in as_completed(futures):
                lat, err = fut.result()
                result.latencies_sec.append(lat)
                if err:
                    result.errors.append(err)
                else:
                    result.ok += 1
    else:
        for t in texts:
            lat, err = _embed_one(t)
            result.latencies_sec.append(lat)
            if err:
                result.errors.append(err)
            else:
                result.ok += 1

    result.wall_sec = time.perf_counter() - t0
    return result


def _print_burst(r: BurstResult) -> None:
    err429 = sum(1 for e in r.errors if "429" in e)
    print(
        f"  {r.label}: n={r.count} ok={r.ok} fail={len(r.errors)} "
        f"429={err429} wall={r.wall_sec:.2f}s eff_rps={r.rps:.1f}"
    )
    if r.p50 is not None:
        print(f"    latency p50={r.p50:.3f}s p95={r.p95:.3f}s max={max(r.latencies_sec):.3f}s")
    if r.errors:
        for e in r.errors[:3]:
            print(f"    error: {e[:200]}")
        if len(r.errors) > 3:
            print(f"    ... +{len(r.errors) - 3} more errors")


def main() -> None:
    print("=== Yandex Embeddings benchmark ===\n")
    print(f"YANDEX_EMBEDDINGS_TRANSPORT: {getattr(config, 'YANDEX_EMBEDDINGS_TRANSPORT', '?')}")
    print(f"YANDEX_EMBEDDING_QUERY_MODEL: {config.YANDEX_EMBEDDING_QUERY_MODEL}")
    print(f"YANDEX_EMBEDDING_RPS_LIMIT: {getattr(config, 'YANDEX_EMBEDDING_RPS_LIMIT', '?')}")
    print(
        f"YANDEX_EMBEDDING_MAX_PARALLEL_REQUESTS: "
        f"{getattr(config, 'YANDEX_EMBEDDING_MAX_PARALLEL_REQUESTS', '?')}"
    )
    print(f"YANDEX_FOLDER_ID: {_mask(config.YANDEX_FOLDER_ID or '')}")
    print(f"API key set: {bool(config.YANDEX_API_KEY or config.YANDEX_IAM_TOKEN)}")
    print()

    if not (config.YANDEX_API_KEY or config.YANDEX_IAM_TOKEN):
        print("ERROR: нет YANDEX_API_KEY / YANDEX_IAM_TOKEN в .env")
        sys.exit(1)

    emb = get_yandex_embeddings()
    if not emb.is_available():
        print("ERROR: YandexEmbeddings SDK не инициализирован")
        sys.exit(1)

    print("[0] warmup …")
    if not warmup_yandex_embeddings():
        print("ERROR: warmup embed_query failed")
        sys.exit(1)
    print("    warmup OK\n")

    print("[1] Одиночные embed_query (5 замеров, последовательно)")
    singles: List[float] = []
    for i in range(5):
        lat, err = _embed_one(_legal_query(i))
        singles.append(lat)
        status = "OK" if not err else f"FAIL: {err[:120]}"
        print(f"    #{i + 1}: {lat:.3f}s  {status}")
    print(f"    median={sorted(singles)[2]:.3f}s\n")

    print("[2] Последовательная пачка (20 запросов)")
    _print_burst(_run_burst("seq×20", 20, parallel=False))
    print()

    print("[3] Параллельные burst (как hybrid справочника)")
    for n in (10, 20, 50):
        _print_burst(_run_burst(f"parallel×{n}", n, parallel=True))
    print()

    print("[4] Симуляция 5 search_queries × 1 embed (5 параллельно, как norm-hybrid)")
    _print_burst(_run_burst("legal_norm_hybrid_sim×5", 5, parallel=True))
    print()

    rps_limit = int(getattr(config, "YANDEX_EMBEDDING_RPS_LIMIT", 10) or 10)
    print("=== Вердикт ===")
    print(
        f"Настроенный RPS_LIMIT={rps_limit}. "
        "Если parallel×50: ok=50 без 429 за ~1-3с — квота ~100/s работает."
    )
    print(
        "Если много 429 или wall>>5с на 20 запросах — лимит в облаке ниже настройки "
        "или очередь/дубли embed в приложении."
    )
    print("\nГотово.")


if __name__ == "__main__":
    main()

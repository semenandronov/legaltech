"""Isolated Python execution for statement ReAct agent (pandas on scope CSV)."""
from __future__ import annotations

import logging
import re
import subprocess
import sys
import textwrap
from dataclasses import dataclass
from pathlib import Path

from app.config import config

logger = logging.getLogger(__name__)

_FORBIDDEN_IMPORT = re.compile(
    r"(?m)^\s*(import|from)\s+"
    r"(os|sys|subprocess|socket|shutil|pathlib|importlib|ctypes|multiprocessing|"
    r"requests|httpx|urllib|pickle|builtins|__builtin__)\b",
    re.IGNORECASE,
)
_FORBIDDEN_CALL = re.compile(
    r"\b(open|exec|eval|compile|__import__|getattr\s*\(\s*__builtins__)\s*\(",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class SandboxRunResult:
    ok: bool
    stdout: str
    stderr: str
    exit_code: int
    truncated: bool = False


def sandbox_timeout_sec() -> int:
    return max(5, int(getattr(config, "STATEMENT_REACT_SANDBOX_TIMEOUT_SEC", 45) or 45))


def max_code_chars() -> int:
    return max(2000, int(getattr(config, "STATEMENT_REACT_MAX_CODE_CHARS", 12000) or 12000))


def max_output_chars() -> int:
    return max(4000, int(getattr(config, "STATEMENT_REACT_MAX_OUTPUT_CHARS", 24000) or 24000))


def validate_user_code(code: str) -> str | None:
    text = (code or "").strip()
    if not text:
        return "Пустой код."
    if len(text) > max_code_chars():
        return f"Код длиннее {max_code_chars()} символов."
    if _FORBIDDEN_IMPORT.search(text):
        return "Запрещены системные импорты (os, sys, subprocess, …)."
    if _FORBIDDEN_CALL.search(text):
        return "Запрещены open/exec/eval и обход builtins."
    return None


_WRAPPER = textwrap.dedent(
    """
    import contextlib
    import io
    import sys
    import traceback

    import pandas as pd

    try:
        import numpy as np
    except ImportError:
        np = None

    from datetime import date, datetime, timedelta

    csv_path = sys.argv[1]
    user_path = sys.argv[2]

    df = pd.read_csv(csv_path)
    namespace = {
        "pd": pd,
        "np": np,
        "df": df,
        "datetime": datetime,
        "date": date,
        "timedelta": timedelta,
        "STATEMENT_CSV": csv_path,
    }

    user_code = open(user_path, encoding="utf-8").read()
    out = io.StringIO()
    err = io.StringIO()
    try:
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            exec(user_code, namespace, namespace)
    except Exception:
        traceback.print_exc(file=err)
        sys.exit(1)

    sys.stdout.write(out.getvalue())
    if err.getvalue().strip():
        sys.stderr.write(err.getvalue())
    """
).strip()


def run_python_in_sandbox(*, code: str, csv_path: Path, work_dir: Path) -> SandboxRunResult:
    err = validate_user_code(code)
    if err:
        return SandboxRunResult(ok=False, stdout="", stderr=err, exit_code=1)

    work_dir.mkdir(parents=True, exist_ok=True)
    user_path = work_dir / "_user_code.py"
    wrapper_path = work_dir / "_sandbox_wrapper.py"
    user_path.write_text(code.strip() + "\n", encoding="utf-8")
    wrapper_path.write_text(_WRAPPER + "\n", encoding="utf-8")

    try:
        completed = subprocess.run(
            [
                sys.executable,
                str(wrapper_path),
                str(csv_path.resolve()),
                str(user_path.resolve()),
            ],
            capture_output=True,
            text=True,
            timeout=sandbox_timeout_sec(),
            cwd=str(work_dir),
            env={
                "PYTHONNOUSERSITE": "1",
                "PYTHONDONTWRITEBYTECODE": "1",
            },
        )
    except subprocess.TimeoutExpired:
        return SandboxRunResult(
            ok=False,
            stdout="",
            stderr=f"Таймаут {sandbox_timeout_sec()} с.",
            exit_code=-1,
        )

    stdout = completed.stdout or ""
    stderr = completed.stderr or ""
    truncated = False
    limit = max_output_chars()
    if len(stdout) > limit:
        stdout = stdout[:limit] + "\n… [stdout обрезан]"
        truncated = True
    if len(stderr) > limit:
        stderr = stderr[:limit] + "\n… [stderr обрезан]"
        truncated = True

    ok = completed.returncode == 0
    if not ok and not stderr.strip():
        stderr = f"exit_code={completed.returncode}"

    logger.info(
        "[StatementSandbox] ok=%s exit=%s out_len=%s",
        ok,
        completed.returncode,
        len(stdout),
    )
    return SandboxRunResult(
        ok=ok,
        stdout=stdout.strip(),
        stderr=stderr.strip(),
        exit_code=completed.returncode,
        truncated=truncated,
    )

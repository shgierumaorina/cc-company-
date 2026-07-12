from __future__ import annotations

import importlib.util
import py_compile
import subprocess
import sys
from pathlib import Path
from typing import Sequence

# 引数なしの場合、この順で最初に存在するディレクトリを検査対象にする
DEFAULT_SOURCE_DIRS = ("src", "scripts")


def run_command(
    command: Sequence[str],
    error_message: str,
) -> tuple[bool, str]:
    """コマンドを実行し、成否とログを返す。"""

    process = subprocess.run(
        command,
        capture_output=True,
        text=True,
        check=False,
    )

    output = "\n".join(
        part
        for part in (
            process.stdout,
            process.stderr,
        )
        if part
    )

    if process.returncode != 0:
        return False, f"{error_message}\n{output}"

    return True, output


def module_available(name: str) -> bool:
    return importlib.util.find_spec(name) is not None


def resolve_source_dirs(args: Sequence[str]) -> list[Path]:
    """引数のディレクトリ、なければデフォルト候補から検査対象を決める。"""

    if args:
        return [Path(arg) for arg in args]

    for candidate in DEFAULT_SOURCE_DIRS:
        path = Path(candidate)
        if path.exists():
            return [path]

    return []


def compile_sources(source_dir: Path) -> tuple[bool, str, int]:
    """ディレクトリ配下の全 .py を py_compile し、成否・ログ・件数を返す。"""

    count = 0
    for file in sorted(source_dir.rglob("*.py")):
        try:
            py_compile.compile(str(file), doraise=True)
        except py_compile.PyCompileError as error:
            return False, f"Syntax check failed: {file}\n{error}", count
        count += 1

    return True, "", count


def verify_implementation(args: Sequence[str]) -> tuple[bool, str]:
    """構文チェック・型チェック・テストで実装品質を検証する。"""

    print("--- Starting Code Verification ---")

    source_dirs = resolve_source_dirs(args)
    checked = 0

    for source_dir in source_dirs:
        if not source_dir.exists():
            return False, f"Source directory not found: {source_dir}"

        print(f"Running py_compile on {source_dir}...")
        success, message, count = compile_sources(source_dir)
        if not success:
            return False, message
        print(f"py_compile passed ({count} files).")
        checked += count

        if module_available("mypy"):
            print(f"Running mypy on {source_dir}...")
            success, message = run_command(
                [sys.executable, "-m", "mypy", str(source_dir)],
                "Type check failed.",
            )
            if not success:
                return False, message
            print("mypy passed.")
        else:
            print("Skipping mypy: not installed.")

    if Path("tests").exists():
        if not module_available("pytest"):
            return False, (
                "tests directory exists but pytest is not installed. "
                "Install pytest or remove the tests directory."
            )

        print("Running pytest...")
        success, message = run_command(
            [sys.executable, "-m", "pytest", "tests", "-q"],
            "Tests failed.",
        )
        if not success:
            return False, message
        print("pytest passed.")
        checked += 1
    else:
        print("Skipping pytest: tests directory not found.")

    if checked == 0:
        return False, (
            "Nothing was verified: no source files found "
            f"(searched: {', '.join(str(d) for d in source_dirs) or DEFAULT_SOURCE_DIRS})."
        )

    return True, "All code quality checks passed."


if __name__ == "__main__":
    passed, result = verify_implementation(sys.argv[1:])

    print(result)

    raise SystemExit(0 if passed else 1)

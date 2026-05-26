#!/usr/bin/env python3
"""PostToolUse hook: форматирует и чинит отредактированный .py файл через ruff.

Читает JSON хука из stdin, достаёт путь к файлу, и если это .py и ruff
установлен — прогоняет `ruff check --fix` и `ruff format`. Любые ошибки
проглатываются, чтобы хук никогда не блокировал работу.
"""
import json
import shutil
import subprocess
import sys


def main() -> int:
    try:
        data = json.load(sys.stdin)
    except Exception:
        return 0
    resp = data.get("tool_response") or {}
    path = resp.get("filePath") or data.get("tool_input", {}).get("file_path", "")
    if not path.endswith(".py"):
        return 0
    ruff = shutil.which("ruff")
    if not ruff:
        return 0
    for args in (["check", "--fix", path], ["format", path]):
        try:
            subprocess.run([ruff, *args], capture_output=True, timeout=30)
        except Exception:
            pass
    return 0


if __name__ == "__main__":
    sys.exit(main())

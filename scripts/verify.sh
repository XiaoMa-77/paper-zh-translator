#!/usr/bin/env bash
# ============================================================
# papertrans 一键校验脚本
# ------------------------------------------------------------
# 依次执行：
#   1. Python 语法编译检查（src / tests / tools）
#   2. ruff lint（如已安装）
#   3. pytest 回归与完整性测试（如已安装）
#   4. 结构级冒烟测试（设置 PAPERTRANS_SAMPLE=<pdf> 可加跑端到端）
# 用法：bash scripts/verify.sh
# ============================================================
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

PY="${PYTHON:-python3}"
command -v "$PY" >/dev/null 2>&1 || PY="python"

green() { printf '\033[32m%s\033[0m\n' "$1"; }
red()   { printf '\033[31m%s\033[0m\n' "$1"; }
step()  { printf '\n=== %s ===\n' "$1"; }

FAILED=0
run() {
  local label="$1"; shift
  step "$label"
  if "$@"; then
    green "✓ $label 通过"
  else
    red "✗ $label 失败"
    FAILED=1
  fi
}
skip() { step "$1"; printf '[跳过] %s\n' "$2"; }

# 依赖提示（不强制安装）
if ! "$PY" -c "import pymupdf, yaml, pdfplumber" >/dev/null 2>&1; then
  printf '[提示] 缺少核心依赖，测试会失败。请执行：pip install -e ".[dev]"\n'
fi

run "Python 语法检查" "$PY" -m compileall -q src tests tools

if command -v ruff >/dev/null 2>&1; then
  run "ruff lint" ruff check src tests tools
else
  skip "ruff lint" "未安装 ruff"
fi

if "$PY" -c "import pytest" >/dev/null 2>&1; then
  run "pytest 回归测试" "$PY" -m pytest -q
else
  skip "pytest 回归测试" "未安装 pytest（pip install -e '.[dev]'）"
fi

run "结构级冒烟测试" "$PY" tests/smoke.py

printf '\n'
if [ "$FAILED" -eq 0 ]; then
  green "全部校验通过"
else
  red "存在失败项，请检查上方输出"
fi
exit "$FAILED"

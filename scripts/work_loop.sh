#!/usr/bin/env bash
set -euo pipefail

ISSUE_NUMBER="${1:?Usage: ./scripts/work_loop.sh <issue-number>}"
MAX_ITERATIONS="${MAX_ITERATIONS:-5}"
MAX_TURNS="${MAX_TURNS:-8}"
MAX_BUDGET_USD="${MAX_BUDGET_USD:-2.00}"

# OmniRoute（ローカルプロキシ、圧縮・キャッシュで節約）経由でclaudeを呼ぶ。このスクリプト内のみ。
export ANTHROPIC_BASE_URL="http://localhost:20128/v1"
export ANTHROPIC_AUTH_TOKEN="omniroute-local"

for ((i = 1; i <= MAX_ITERATIONS; i++)); do
  echo "--- Iteration ${i}/${MAX_ITERATIONS} ---"

  claude -p \
    --max-turns "$MAX_TURNS" \
    --max-budget-usd "$MAX_BUDGET_USD" \
    "GitHub Issue #${ISSUE_NUMBER}を読み、実装してください。完了前にpython verify_code_quality.pyを実行し、失敗した場合は修正してください。"

  if python verify_code_quality.py; then
    echo "Verification passed."
    exit 0
  fi
done

echo "Maximum iterations reached. Manual review is required."
exit 1

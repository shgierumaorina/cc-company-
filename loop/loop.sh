#!/bin/bash
# loop.sh — 1回の実行 = 1 tick。
#   triage -> conductor -> implement -> verify を順番に呼び出し、
#   各段階のコストを loop/logs/cost-YYYY-MM-DD.tsv に記録する。
#   その日の累計コストが DAILY_BUDGET_USD を超えていたら何もせず停止する。
#
# 使い方:  bash loop/loop.sh
# 環境変数: DAILY_BUDGET_USD (default 3.00)
#           TRIAGE_MODEL / CONDUCTOR_MODEL / WORKER_MODEL

set -euo pipefail
cd "$(dirname "$0")/.."   # repo root

LOOP_DIR="loop"
LOG_DIR="$LOOP_DIR/logs"
STATE_DIR="$LOOP_DIR/state"
mkdir -p "$LOG_DIR" "$STATE_DIR"
touch "$STATE_DIR/trust-ledger.md" "$STATE_DIR/queue.md" "$STATE_DIR/questions.md"

TODAY="$(date +%F)"
COST_LOG="$LOG_DIR/cost-$TODAY.tsv"          # 列: 時刻 <TAB> tick <TAB> stage <TAB> USD
TICK_LOG="$LOG_DIR/tick-$TODAY.log"
TICK_ID="$(date +%H%M%S)"

DAILY_BUDGET_USD="${DAILY_BUDGET_USD:-3.00}"
TRIAGE_MODEL="${TRIAGE_MODEL:-claude-haiku-4-5-20251001}"
CONDUCTOR_MODEL="${CONDUCTOR_MODEL:-claude-fable-5}"
WORKER_MODEL="${WORKER_MODEL:-claude-sonnet-4-6}"

# OmniRoute（ローカルプロキシ、圧縮・キャッシュで節約）経由でclaudeを呼ぶ。このスクリプト内のみ。
export ANTHROPIC_BASE_URL="http://localhost:20128/v1"
export ANTHROPIC_AUTH_TOKEN="omniroute-local"

log() { printf '[%s] %s\n' "$(date +%T)" "$*" | tee -a "$TICK_LOG" >&2; }

py_json() {  # stdin の JSON から $1 のキーを取り出す（無ければ空）
  python -c "import json,sys; print(json.load(sys.stdin).get('$1',''))" 2>/dev/null || true
}

spent_today() {
  awk -F'\t' '{s+=$4} END{printf "%.4f", s+0}' "$COST_LOG" 2>/dev/null || printf '0'
}

check_budget() {
  local s; s="$(spent_today)"
  if python -c "import sys; sys.exit(0 if float('$s') >= float('$DAILY_BUDGET_USD') else 1)"; then
    log "BUDGET EXCEEDED: 本日累計 \$$s >= 予算 \$$DAILY_BUDGET_USD — 停止"
    exit 2
  fi
}

# run_stage <stage名> <model> <プロンプトファイル> <追加入力> [claudeフラグ...]
# 標準出力に result テキストを返し、コストをログに記録する。
run_stage() {
  local stage="$1" model="$2" prompt_file="$3" input="$4"; shift 4
  check_budget
  log "stage=$stage model=$model 開始"

  local raw cost result
  raw="$(printf '%s\n\n---INPUT---\n%s\n' "$(cat "$prompt_file")" "$input" \
        | claude -p --model "$model" --output-format json "$@")" || {
    log "stage=$stage: claude 実行失敗"
    return 1
  }
  cost="$(printf '%s' "$raw" | py_json total_cost_usd)"; cost="${cost:-0}"
  result="$(printf '%s' "$raw" | py_json result)"

  printf '%s\t%s\t%s\t%s\n' "$(date +%T)" "$TICK_ID" "$stage" "$cost" >> "$COST_LOG"
  log "stage=$stage 完了 cost=\$$cost (本日累計 \$$(spent_today))"
  printf '%s' "$result"
}

# ---------------------------------------------------------------- tick 開始
check_budget
log "=== tick $TICK_ID 開始 (予算 \$$DAILY_BUDGET_USD / 使用済 \$$(spent_today)) ==="

# 1. triage（読み取り専用・安いモデル）
TRIAGE_OUT="$(run_stage triage "$TRIAGE_MODEL" "$LOOP_DIR/triage.md" "" \
  --allowedTools "Read,Grep,Glob,Bash(git log:*),Bash(gh issue list:*),Bash(gh run list:*)")"
log "triage 出力: $TRIAGE_OUT"

if printf '%s' "$TRIAGE_OUT" | grep -q '^status: quiet' && ! grep -q '[^[:space:]]' "$STATE_DIR/queue.md"; then
  log "quiet かつ queue も空 — conductor を呼ばず tick 終了"
  exit 0
fi

# 2. conductor（採配のみ・Fable 5）
CONDUCTOR_INPUT="## triage の出力
$TRIAGE_OUT

## loop/contract.md
$(cat "$LOOP_DIR/contract.md")

## 信頼台帳 (trust-ledger.md)
$(cat "$STATE_DIR/trust-ledger.md")

## queue.md
$(cat "$STATE_DIR/queue.md")"

DECISION="$(run_stage conductor "$CONDUCTOR_MODEL" "$LOOP_DIR/conductor.md" "$CONDUCTOR_INPUT" \
  --allowedTools "Read")"
log "conductor 出力: $DECISION"

ACTION="$(printf '%s' "$DECISION" | py_json action)"
ITEM="$(printf '%s' "$DECISION" | py_json item)"

case "$ACTION" in
  stop)
    log "conductor 判断: stop — $ITEM"
    printf -- '- [%s %s] STOP: %s\n' "$TODAY" "$TICK_ID" "$ITEM" >> "$STATE_DIR/trust-ledger.md"
    exit 0 ;;
  queue)
    log "conductor 判断: queue — $ITEM"
    printf -- '- [%s %s] 承認待ち: %s\n' "$TODAY" "$TICK_ID" "$ITEM" >> "$STATE_DIR/queue.md"
    exit 0 ;;
  execute) ;;
  *)
    log "conductor の出力が不正 (action='$ACTION') — tick 中断"
    exit 1 ;;
esac

# 3. implement（Sonnet ワーカー）
IMPL_OUT="$(run_stage implement "$WORKER_MODEL" "$LOOP_DIR/workers/implement.md" "$DECISION" \
  --permission-mode acceptEdits \
  --allowedTools "Read,Grep,Glob,Edit,Write,Bash(git diff:*),Bash(git status:*),Bash(git log:*),Bash(python:*)")"
log "implement 出力: $IMPL_OUT"

if printf '%s' "$IMPL_OUT" | grep -q '^BLOCKED:'; then
  log "implement がブロック — questions.md を確認すること"
  printf -- '- [%s %s] BLOCKED: %s\n' "$TODAY" "$TICK_ID" "$ITEM" >> "$STATE_DIR/trust-ledger.md"
  exit 0
fi

# 4. verify（仕様と diff だけで判定）
VERIFY_INPUT="## conductor の作業指示 (spec / done_when)
$DECISION

## 作業後の diff
$(git diff; git diff --cached)"

VERDICT="$(run_stage verify "$WORKER_MODEL" "$LOOP_DIR/workers/verify.md" "$VERIFY_INPUT" \
  --allowedTools "Read,Grep,Glob,Bash(git diff:*),Bash(python:*)")"
log "verify 判定: $VERDICT"

# 信頼台帳へ記録
printf -- '- [%s %s] %s | %s\n' "$TODAY" "$TICK_ID" "$VERDICT" "$ITEM" >> "$STATE_DIR/trust-ledger.md"

log "=== tick $TICK_ID 終了 (本日累計 \$$(spent_today)) ==="
if printf '%s' "$VERDICT" | grep -q '^PASS:'; then exit 0; else exit 1; fi

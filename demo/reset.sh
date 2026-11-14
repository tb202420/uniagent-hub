#!/usr/bin/env bash
# 演示重置（POSIX）：清理两次演示之间的进程与状态，目标 5 秒内完成
# 用法：bash demo/reset.sh
set -e
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
RUN_DIR="$ROOT/data/demo_runs"

if [ -d "$RUN_DIR" ]; then
  for f in "$RUN_DIR"/irrigation_approval_*.pids; do
    [ -e "$f" ] || continue
    while IFS= read -r pid; do
      [ -n "$pid" ] && kill -9 "$pid" 2>/dev/null || true
    done < "$f"
    rm -f "$f"
  done
fi

rm -f "$ROOT"/data/demo_irrigation.db* "$ROOT"/data/demo_irrigation_audit.jsonl
echo "[reset] 演示进程已清理，审批状态/演示库/审计已重置（证据日志保留在 data/demo_runs）"

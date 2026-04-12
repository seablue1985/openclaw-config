#!/bin/bash
# Skill Evolver — 每日定时回顾
# 每天 21:00 执行

DATE_STR=$(date +%Y-%m-%d)
SKILL_DIR="$(cd "$(dirname "$0")" && cd .. && pwd)"
LOG_FILE="$HOME/.openclaw/workspace/memory/skill_evolution_log.md"

echo "[$(date '+%Y-%m-%d %H:%M')] 开始 Skill Evolver 每日回顾" >> "$SKILL_DIR/logs/daily_review.log" 2>&1

cd "$SKILL_DIR" || exit 1

RESULT=$(node scripts/skill_evolver.js --mode=review --date="$DATE_STR" 2>&1)
echo "$RESULT" >> "$SKILL_DIR/logs/daily_review.log" 2>&1

echo "$RESULT"

# 如果有候选机会，记录并输出摘要供 cron 推送
if echo "$RESULT" | grep -q "候选"; then
  echo "[$(date '+%Y-%m-%d %H:%M')] 回顾完成，有候选沉淀机会" >> "$SKILL_DIR/logs/daily_review.log"
else
  echo "[$(date '+%Y-%m-%d %H:%M')] 回顾完成，无新增沉淀机会" >> "$SKILL_DIR/logs/daily_review.log"
fi

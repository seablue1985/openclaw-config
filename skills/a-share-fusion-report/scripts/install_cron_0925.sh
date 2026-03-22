#!/bin/bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
RUNNER="$SCRIPT_DIR/run_fusion_report.py"
LOG_FILE="/tmp/a-share-fusion-report.log"

if [[ ! -f "$RUNNER" ]]; then
  echo "Runner not found: $RUNNER"
  exit 1
fi

TMP_CRON=$(mktemp)
(crontab -l 2>/dev/null || true) | grep -v "A_SHARE_FUSION_REPORT_0925" > "$TMP_CRON"
echo "25 9 * * 1-5 python3 $RUNNER --trading-day-only --push-feishu >> $LOG_FILE 2>&1 # A_SHARE_FUSION_REPORT_0925" >> "$TMP_CRON"
crontab "$TMP_CRON"
rm -f "$TMP_CRON"

echo "Installed cron: A_SHARE_FUSION_REPORT_0925"
crontab -l | grep "A_SHARE_FUSION_REPORT_0925" || true

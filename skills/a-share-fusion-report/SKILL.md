---
name: a-share-fusion-report
description: "Generate a unified A-share report by combining three installed skills: stock-daily-report (HTML/PNG professional report), stock-watcher (fast structured quote fallback), and akshare-stock (fund-flow overlay). Use when you need one reliable daily report from current holdings, automatic fallback if one data source fails, and optional Feishu push (especially for trading-day 09:25 automation)."
---

# A-Share Fusion Report

Run this skill when you want one consolidated output instead of manually running multiple stock skills.

## What this skill does

1. Loads holdings codes from your latest portfolio source (priority):
   - `quant_projects/personal-a-share-research-system/research/reports/ths_web_holding_count_fix_*.json`
   - fallback: `.../ths_app_holdings_*.csv`
2. Syncs watchlists to both engines:
   - `skills/stock-daily-report/config.json`
   - `~/.clawdbot/stock_watcher/watchlist.txt`
3. Generates a professional report via `stock-daily-report`.
4. Adds fallback quote lines from `stock-watcher`.
5. Adds `akshare-stock` fund-flow overlay (top-N symbols).
6. Outputs merged markdown + json summary and can push to Feishu.

## Commands

### A) Fast local test (no push)

```bash
python3 skills/a-share-fusion-report/scripts/run_fusion_report.py --limit 5
```

### B) Full holdings run + Feishu push

```bash
python3 skills/a-share-fusion-report/scripts/run_fusion_report.py --push-feishu
```

### C) Trading-day only guard

```bash
python3 skills/a-share-fusion-report/scripts/run_fusion_report.py --trading-day-only --push-feishu
```

### D) Install 09:25 weekday cron

```bash
bash skills/a-share-fusion-report/scripts/install_cron_0925.sh
```

## Key output

Default output directory:
`quant_projects/personal-a-share-research-system/research/reports`

Generated files:
- `a-share-fusion-report_YYYYMMDD_HHMMSS.md`
- `a-share-fusion-report_YYYYMMDD_HHMMSS.json`
- plus `stock-daily-report` generated HTML/PNG files

## Notes

- The script keeps non-6-digit codes (e.g. HK) in universe logs but only sends 6-digit symbols to A-share engines.
- If `stock-daily-report` fails, fallback quote lines from `stock-watcher` are still captured in the merged report.
- If akshare network is unstable, report still succeeds with partial overlay.

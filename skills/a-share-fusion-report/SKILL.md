---
name: a-share-fusion-report
description: "Generate a unified A-share report by combining three installed skills: stock-daily-report (HTML/PNG professional report), stock-watcher (fast structured quote fallback), and akshare-stock (fund-flow overlay). Use when you need one reliable daily report from current holdings, automatic fallback if one data source fails, and optional Feishu push (especially for trading-day 09:25 automation)."
---

# A-Share Fusion Report

Run this skill when you want one consolidated output instead of manually running multiple stock skills.

## What this skill does

1. Loads holdings codes from one source, in order of priority:
   - explicit `--input-file` (`json/csv/xlsx/xls/txt`)
   - explicit `--codes`
   - autodiscovery from latest portfolio source:
     - `quant_projects/personal-a-share-research-system/research/reports/ths_web_holding_count_fix_*.json`
     - fallback: `.../ths_app_holdings_*.csv`
2. Centralizes input parsing, validation, and input snapshots.
3. Syncs watchlists to both engines:
   - `workspace/skills/stock-daily-report/config.json`
   - `~/.clawdbot/stock_watcher/watchlist.txt`
4. Generates a professional report via `stock-daily-report`.
5. Adds fallback quote lines from `stock-watcher`.
6. Adds `akshare-stock` fund-flow overlay (top-N symbols).
7. Writes stable artifacts for each run and updates latest pointers.

## Commands

### A) Fast local test with inline codes

```bash
python3 skills/a-share-fusion-report/scripts/run_fusion_report.py --codes 600519,000001 --limit 2
```

### B) Run from explicit holdings Excel

```bash
python3 skills/a-share-fusion-report/scripts/run_fusion_report.py \
  --input-file ~/.openclaw/media/inbound/shares---a2a3de8e-91a6-41a7-b3a4-0e928661a43e.xlsx \
  --limit 5
```

### C) Full holdings run + Feishu push

```bash
python3 skills/a-share-fusion-report/scripts/run_fusion_report.py --push-feishu
```

### D) Trading-day only guard

```bash
python3 skills/a-share-fusion-report/scripts/run_fusion_report.py --trading-day-only --push-feishu
```

### E) Fail-closed example (no 6-digit A-share codes)

```bash
python3 skills/a-share-fusion-report/scripts/run_fusion_report.py --codes 2188,2316
```

### F) Install 09:25 weekday cron

```bash
bash skills/a-share-fusion-report/scripts/install_cron_0925.sh
```

## Key output

Default output directory:
`quant_projects/personal-a-share-research-system/research/reports`

Per-run stable artifacts:
- `a-share-fusion-report_runs/<RUN_ID>/input_snapshot.json`
- `a-share-fusion-report_runs/<RUN_ID>/input_snapshot.csv`
- `a-share-fusion-report_runs/<RUN_ID>/summary.json`
- `a-share-fusion-report_runs/<RUN_ID>/report.md`
- `a-share-fusion-report_runs/<RUN_ID>/run_summary.txt`

Latest stable pointers:
- `a-share-fusion-report_latest_input_snapshot.json`
- `a-share-fusion-report_latest_input_snapshot.csv`
- `a-share-fusion-report_latest_summary.json`
- `a-share-fusion-report_latest.md`
- `a-share-fusion-report_latest_run_summary.txt`

Compatibility outputs retained:
- `a-share-fusion-report_<RUN_ID>.md`
- `a-share-fusion-report_<RUN_ID>.json`
- plus `stock-daily-report_<RUN_ID>.html/.png` when available

## Fail-closed rules

The script stops with non-zero exit when:
- no holdings source can be found
- the input file is missing / unsupported / schema-unreadable
- no normalized stock codes can be extracted
- no 6-digit A-share codes remain after parsing
- `stock-daily-report` and `stock-watcher` both fail in the same run

## Notes

- Non-6-digit codes (e.g. HK) are preserved in input snapshots and run metadata, but only 6-digit A-share symbols are sent to A-share engines.
- `stock-daily-report` is treated as a preferred engine, not the only engine: if it fails but `stock-watcher` succeeds, the run is marked `SUCCESS_WITH_FALLBACK`.
- `akshare-stock` overlay is best-effort; partial failures are captured in the run summary instead of silently dropped.

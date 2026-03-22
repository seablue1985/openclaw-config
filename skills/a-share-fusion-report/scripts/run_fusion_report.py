#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import json
import os
import re
import subprocess
from datetime import date, datetime
from pathlib import Path
from typing import Any

WORKSPACE = Path.home() / ".openclaw" / "workspace"
DEFAULT_OUTPUT_DIR = (
    WORKSPACE / "quant_projects" / "personal-a-share-research-system" / "research" / "reports"
)
STOCK_DAILY_DIR = WORKSPACE / "skills" / "stock-daily-report"
STOCK_DAILY_CONFIG = STOCK_DAILY_DIR / "config.json"
STOCK_WATCHER_WATCHLIST = Path.home() / ".clawdbot" / "stock_watcher" / "watchlist.txt"
AKSHARE_STOCK_CLI = Path.home() / ".openclaw" / "skills" / "akshare-stock" / "scripts" / "stock_cli.py"
STOCK_WATCHER_SUMMARY = (
    Path.home() / ".openclaw" / "skills" / "stock-watcher" / "scripts" / "summarize_performance.py"
)


def normalize_code(raw: Any) -> str | None:
    s = str(raw or "").strip().upper()
    if not s:
        return None
    # SH600519 / SZ000001 -> digits
    if len(s) >= 8 and s[:2] in {"SH", "SZ", "BJ", "HK"} and s[2:].isdigit():
        s = s[2:]
    # 600519.SH -> 600519
    if "." in s:
        s = s.split(".", 1)[0]

    s = re.sub(r"\D", "", s)
    if len(s) in {5, 6}:
        return s
    return None


def latest_file(root: Path, pattern: str) -> Path | None:
    files = [p for p in root.glob(pattern) if p.is_file()]
    if not files:
        return None
    files.sort(key=lambda p: p.stat().st_mtime, reverse=True)
    return files[0]


def load_codes_from_web_fix(report_dir: Path) -> tuple[list[str], str]:
    p = latest_file(report_dir, "ths_web_holding_count_fix_*.json")
    if not p:
        return [], ""
    try:
        payload = json.loads(p.read_text(encoding="utf-8"))
        codes = [normalize_code(x) for x in (payload.get("codes") or [])]
        codes = [c for c in codes if c]
        return dedupe(codes), str(p)
    except Exception:
        return [], str(p)


def load_codes_from_local_holdings(report_dir: Path) -> tuple[list[str], str]:
    p = latest_file(report_dir, "ths_app_holdings_*.csv")
    if not p:
        return [], ""

    codes: list[str] = []
    try:
        with p.open("r", encoding="utf-8-sig", newline="") as f:
            reader = csv.DictReader(f)
            for row in reader:
                code = normalize_code(row.get("symbol"))
                if code:
                    codes.append(code)
    except Exception:
        return [], str(p)

    return dedupe(codes), str(p)


def dedupe(items: list[str]) -> list[str]:
    seen = set()
    out: list[str] = []
    for x in items:
        if x in seen:
            continue
        seen.add(x)
        out.append(x)
    return out


def split_a_share(codes: list[str]) -> tuple[list[str], list[str]]:
    a_share = [c for c in codes if len(c) == 6]
    non_a = [c for c in codes if len(c) != 6]
    return a_share, non_a


def sync_stock_daily_config(codes_6d: list[str], output_dir: Path) -> None:
    STOCK_DAILY_DIR.mkdir(parents=True, exist_ok=True)

    cfg: dict[str, Any] = {}
    if STOCK_DAILY_CONFIG.exists():
        try:
            cfg = json.loads(STOCK_DAILY_CONFIG.read_text(encoding="utf-8"))
        except Exception:
            cfg = {}

    cfg["stocks"] = [{"code": c, "name": c} for c in codes_6d]
    cfg.setdefault("report_prefix", "stock-daily-report")
    cfg.setdefault("output_format", "both")
    cfg["output_dir"] = str(output_dir)

    STOCK_DAILY_CONFIG.write_text(json.dumps(cfg, ensure_ascii=False, indent=2), encoding="utf-8")


def sync_stock_watcher_watchlist(codes: list[str]) -> None:
    STOCK_WATCHER_WATCHLIST.parent.mkdir(parents=True, exist_ok=True)
    lines = [f"{c}|{c}" for c in codes]
    STOCK_WATCHER_WATCHLIST.write_text("\n".join(lines) + "\n", encoding="utf-8")


def run_cmd(cmd: list[str], cwd: Path | None = None, timeout: int = 300) -> tuple[int, str, str]:
    p = subprocess.run(
        cmd,
        cwd=str(cwd) if cwd else None,
        capture_output=True,
        text=True,
        timeout=timeout,
    )
    return p.returncode, p.stdout or "", p.stderr or ""


def run_stock_daily_report(codes_6d: list[str], output_dir: Path, report_prefix: str) -> dict[str, Any]:
    if not codes_6d:
        return {"ok": False, "reason": "no_6digit_a_share_codes"}

    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    output_base = output_dir / f"{report_prefix}_{ts}"
    cmd = [
        "python3",
        "generate_report.py",
        "--stocks",
        ",".join(codes_6d),
        "--format",
        "both",
        "--output",
        str(output_base),
    ]
    rc, out, err = run_cmd(cmd, cwd=STOCK_DAILY_DIR, timeout=900)

    html_file = Path(str(output_base) + ".html")
    img_file = Path(str(output_base) + ".png")

    return {
        "ok": rc == 0 and html_file.exists(),
        "returncode": rc,
        "stdout_tail": "\n".join(out.strip().splitlines()[-20:]),
        "stderr_tail": "\n".join(err.strip().splitlines()[-20:]),
        "html_file": str(html_file) if html_file.exists() else "",
        "image_file": str(img_file) if img_file.exists() else "",
    }


def run_stock_watcher_summary() -> dict[str, Any]:
    if not STOCK_WATCHER_SUMMARY.exists():
        return {"ok": False, "reason": "stock_watcher_not_installed"}

    rc, out, err = run_cmd(["python3", str(STOCK_WATCHER_SUMMARY)], timeout=240)
    lines = [ln for ln in out.splitlines() if ln.strip()]
    return {
        "ok": rc == 0 and len(lines) > 0,
        "returncode": rc,
        "lines": lines[:120],
        "stderr_tail": "\n".join(err.strip().splitlines()[-20:]),
    }


def fetch_akshare_flow(code: str) -> dict[str, Any] | None:
    if not AKSHARE_STOCK_CLI.exists():
        return None

    rc, out, _ = run_cmd(["python3", str(AKSHARE_STOCK_CLI), "flow", "--symbol", code], timeout=120)
    if rc != 0:
        return None
    try:
        rows = json.loads(out)
        if not isinstance(rows, list) or not rows:
            return None
        row = rows[0]
        return {
            "code": code,
            "date": row.get("日期"),
            "close": row.get("收盘价"),
            "pct": row.get("涨跌幅"),
            "main_inflow": row.get("主力净流入-净额"),
            "main_inflow_ratio": row.get("主力净流入-净占比"),
        }
    except Exception:
        return None


def is_trading_day() -> bool:
    try:
        import akshare as ak  # type: ignore

        today = date.today().strftime("%Y-%m-%d")
        df = ak.tool_trade_date_hist_sina()
        s = set(df["trade_date"].dt.strftime("%Y-%m-%d").tolist())
        return today in s
    except Exception:
        return date.today().weekday() < 5


def push_to_feishu(target_user: str, message: str, image_file: str = "") -> tuple[bool, str]:
    cmd = [
        "openclaw",
        "message",
        "send",
        "--channel",
        "feishu",
        "--account",
        "default",
        "--target",
        target_user,
        "-m",
        message,
    ]
    if image_file and Path(image_file).exists():
        cmd.extend(["--media", image_file])

    rc, out, err = run_cmd(cmd, timeout=90)
    ok = rc == 0
    info = (out.strip() or err.strip())[-1000:]
    return ok, info


def build_markdown(
    out_file: Path,
    source_file: str,
    all_codes: list[str],
    a_share_codes: list[str],
    non_a_codes: list[str],
    stock_daily: dict[str, Any],
    watcher: dict[str, Any],
    flow_rows: list[dict[str, Any]],
) -> None:
    lines = [
        f"# A-Share Fusion Report ({datetime.now().strftime('%Y-%m-%d %H:%M:%S')})",
        "",
        "## Universe",
        f"- Source: `{source_file or '-'}'",
        f"- Total holdings codes: **{len(all_codes)}**",
        f"- A-share 6-digit codes: **{len(a_share_codes)}**",
    ]
    if non_a_codes:
        lines.append(f"- Non A-share / unsupported codes: `{', '.join(non_a_codes)}`")

    lines += [
        "",
        "## Report Engine (stock-daily-report)",
        f"- Status: **{'OK' if stock_daily.get('ok') else 'FAILED'}**",
        f"- HTML: `{stock_daily.get('html_file', '') or '-'}`",
        f"- Image: `{stock_daily.get('image_file', '') or '-'}`",
    ]

    lines += [
        "",
        "## Fast Quotes Fallback (stock-watcher)",
        f"- Status: **{'OK' if watcher.get('ok') else 'FAILED'}**",
    ]
    for ln in (watcher.get("lines") or [])[:15]:
        lines.append(f"- {ln}")

    lines += ["", "## Professional Overlay (akshare fund flow)"]
    if flow_rows:
        lines += [
            "",
            "| code | date | close | pct | main_inflow | main_inflow_ratio |",
            "|---|---|---:|---:|---:|---:|",
        ]
        for r in flow_rows:
            lines.append(
                f"| {r.get('code')} | {r.get('date')} | {r.get('close')} | {r.get('pct')} | {r.get('main_inflow')} | {r.get('main_inflow_ratio')} |"
            )
    else:
        lines.append("- 暂无可用资金流数据（网络/接口限制）。")

    out_file.write_text("\n".join(lines), encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description="Fuse stock-watcher + akshare-stock + stock-daily-report")
    parser.add_argument("--codes", default="", help="Override codes, comma-separated")
    parser.add_argument("--limit", type=int, default=0, help="Limit number of A-share codes for fast testing")
    parser.add_argument("--output-dir", default=str(DEFAULT_OUTPUT_DIR))
    parser.add_argument("--report-prefix", default="a-share-fusion-report")
    parser.add_argument("--akshare-top", type=int, default=8)
    parser.add_argument("--push-feishu", action="store_true")
    parser.add_argument("--target-user", default="user:ou_968a615509dc191f04220e18cda67080")
    parser.add_argument("--trading-day-only", action="store_true")
    args = parser.parse_args()

    if args.trading_day_only and not is_trading_day():
        print(json.dumps({"status": "SKIP_NON_TRADING_DAY", "date": str(date.today())}, ensure_ascii=False, indent=2))
        return

    output_dir = Path(args.output_dir).expanduser().resolve()
    output_dir.mkdir(parents=True, exist_ok=True)

    if args.codes.strip():
        all_codes = dedupe([c for c in (normalize_code(x) for x in args.codes.split(",")) if c])
        source_file = "--codes"
    else:
        codes, source_file = load_codes_from_web_fix(output_dir)
        if not codes:
            codes, source_file = load_codes_from_local_holdings(output_dir)
        all_codes = codes

    a_share_codes, non_a_codes = split_a_share(all_codes)
    if args.limit and args.limit > 0:
        a_share_codes = a_share_codes[: args.limit]

    sync_stock_daily_config(a_share_codes, output_dir)
    sync_stock_watcher_watchlist(all_codes)

    stock_daily = run_stock_daily_report(a_share_codes, output_dir, args.report_prefix)
    watcher = run_stock_watcher_summary()

    flow_rows: list[dict[str, Any]] = []
    for c in a_share_codes[: max(0, args.akshare_top)]:
        row = fetch_akshare_flow(c)
        if row:
            flow_rows.append(row)

    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    md_file = output_dir / f"{args.report_prefix}_{ts}.md"
    json_file = output_dir / f"{args.report_prefix}_{ts}.json"

    build_markdown(
        out_file=md_file,
        source_file=source_file,
        all_codes=all_codes,
        a_share_codes=a_share_codes,
        non_a_codes=non_a_codes,
        stock_daily=stock_daily,
        watcher=watcher,
        flow_rows=flow_rows,
    )

    result = {
        "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "source_file": source_file,
        "all_codes": all_codes,
        "a_share_codes": a_share_codes,
        "non_a_codes": non_a_codes,
        "stock_daily": stock_daily,
        "stock_watcher": {
            "ok": watcher.get("ok", False),
            "sample": (watcher.get("lines") or [])[:5],
        },
        "akshare_flow_rows": flow_rows,
        "output": {
            "markdown": str(md_file),
            "json": str(json_file),
        },
    }

    if args.push_feishu:
        msg = (
            "📈 A股融合报告已生成\n"
            f"- 持仓代码数: {len(all_codes)}\n"
            f"- A股代码数: {len(a_share_codes)}\n"
            f"- HTML: {stock_daily.get('html_file') or '-'}\n"
            f"- MD: {md_file}"
        )
        ok, info = push_to_feishu(
            target_user=args.target_user,
            message=msg,
            image_file=stock_daily.get("image_file", ""),
        )
        result["feishu_push"] = {"ok": ok, "info": info}

    json_file.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()

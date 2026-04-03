#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import json
import re
import shutil
import subprocess
import sys
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Any

WORKSPACE = Path.home() / ".openclaw" / "workspace"
DEFAULT_OUTPUT_DIR = (
    WORKSPACE / "quant_projects" / "personal-a-share-research-system" / "research" / "reports"
)
STOCK_DAILY_DIR = WORKSPACE / "skills" / "stock-daily-report"
STOCK_DAILY_ENTRY = STOCK_DAILY_DIR / "generate_report.py"
STOCK_DAILY_CONFIG = STOCK_DAILY_DIR / "config.json"
STOCK_WATCHER_WATCHLIST = Path.home() / ".clawdbot" / "stock_watcher" / "watchlist.txt"
AKSHARE_STOCK_CLI = Path.home() / ".openclaw" / "skills" / "akshare-stock" / "scripts" / "stock_cli.py"
STOCK_WATCHER_SUMMARY = (
    Path.home() / ".openclaw" / "skills" / "stock-watcher" / "scripts" / "summarize_performance.py"
)
AUTODISCOVER_PATTERNS: list[tuple[str, str]] = [
    ("ths_web_selected_holdings_latest.json", "ths_web_selected_holdings"),
    ("ths_web_selected_holdings_*.json", "ths_web_selected_holdings"),
    ("ths_web_holding_count_fix_*.json", "ths_web_holding_count_fix"),
    ("ths_app_holdings_*.csv", "ths_app_holdings"),
]
CODE_FIELD_CANDIDATES = [
    "code",
    "symbol",
    "ticker",
    "stock_code",
    "security_code",
    "证券代码",
    "股票代码",
    "代码",
    "证券",
]


class FusionReportError(RuntimeError):
    def __init__(
        self,
        code: str,
        message: str,
        *,
        details: dict[str, Any] | None = None,
        exit_code: int = 2,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.details = details or {}
        self.exit_code = exit_code

    def to_payload(self) -> dict[str, Any]:
        return {
            "code": self.code,
            "message": self.message,
            "details": self.details,
            "exit_code": self.exit_code,
        }


@dataclass
class InputBundle:
    source_kind: str
    source_file: str
    source_label: str
    rows: list[dict[str, Any]]
    all_codes: list[str]
    a_share_codes: list[str]
    non_a_codes: list[str]
    invalid_rows: list[dict[str, Any]]
    selected_a_share_codes: list[str]


@dataclass
class RunArtifacts:
    run_id: str
    run_dir: Path
    input_snapshot_json: Path
    input_snapshot_csv: Path
    report_md: Path
    summary_json: Path
    run_summary_txt: Path
    legacy_report_md: Path
    legacy_summary_json: Path
    latest_report_md: Path
    latest_summary_json: Path
    latest_run_summary_txt: Path
    latest_input_snapshot_json: Path
    latest_input_snapshot_csv: Path


def normalize_code(raw: Any) -> str | None:
    s = str(raw or "").strip().upper()
    if not s or s in {"NAN", "NONE", "NULL"}:
        return None
    if len(s) >= 8 and s[:2] in {"SH", "SZ", "BJ", "HK"} and s[2:].isdigit():
        s = s[2:]
    if "." in s:
        s = s.split(".", 1)[0]
    s = re.sub(r"\D", "", s)
    if len(s) in {5, 6}:
        return s
    return None



def normalize_header(raw: Any) -> str:
    return re.sub(r"[\s_\-]+", "", str(raw or "")).strip().lower()



def classify_code(code: str | None) -> str:
    if not code:
        return "invalid"
    if len(code) == 6:
        return "a_share_6d"
    return "non_a_share_or_other"



def dedupe(items: list[str]) -> list[str]:
    seen = set()
    out: list[str] = []
    for item in items:
        if item in seen:
            continue
        seen.add(item)
        out.append(item)
    return out



def latest_file(root: Path, pattern: str) -> Path | None:
    files = [p for p in root.glob(pattern) if p.is_file()]
    if not files:
        return None
    files.sort(key=lambda p: p.stat().st_mtime, reverse=True)
    return files[0]



def safe_tail(text: str, lines: int = 20) -> str:
    items = [line for line in (text or "").splitlines()]
    return "\n".join(items[-lines:])



def json_safe(value: Any) -> Any:
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, dict):
        return {str(k): json_safe(v) for k, v in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [json_safe(v) for v in value]
    return str(value)



def preferred_code_field(rows: list[dict[str, Any]]) -> str | None:
    headers: dict[str, str] = {}
    for row in rows:
        for key in row.keys():
            norm = normalize_header(key)
            if norm and norm not in headers:
                headers[norm] = key
    for candidate in CODE_FIELD_CANDIDATES:
        actual = headers.get(normalize_header(candidate))
        if actual:
            return actual
    return None



def build_bundle_from_code_list(
    codes: list[Any],
    *,
    source_kind: str,
    source_file: str,
    source_label: str,
) -> InputBundle:
    rows: list[dict[str, Any]] = []
    normalized_codes: list[str] = []
    a_share_codes: list[str] = []
    non_a_codes: list[str] = []
    invalid_rows: list[dict[str, Any]] = []

    for index, raw_code in enumerate(codes, start=1):
        normalized = normalize_code(raw_code)
        classification = classify_code(normalized)
        row = {
            "row_index": index,
            "raw_code": str(raw_code),
            "normalized_code": normalized,
            "classification": classification,
            "raw_row": {"code": json_safe(raw_code)},
        }
        rows.append(row)
        if not normalized:
            invalid_rows.append(row)
            continue
        normalized_codes.append(normalized)
        if len(normalized) == 6:
            a_share_codes.append(normalized)
        else:
            non_a_codes.append(normalized)

    return InputBundle(
        source_kind=source_kind,
        source_file=source_file,
        source_label=source_label,
        rows=rows,
        all_codes=dedupe(normalized_codes),
        a_share_codes=dedupe(a_share_codes),
        non_a_codes=dedupe(non_a_codes),
        invalid_rows=invalid_rows,
        selected_a_share_codes=[],
    )



def build_bundle_from_rows(
    rows: list[dict[str, Any]],
    *,
    source_kind: str,
    source_file: str,
    source_label: str,
) -> InputBundle:
    code_field = preferred_code_field(rows)
    if not code_field:
        raise FusionReportError(
            "input_schema_unsupported",
            "无法从输入表中识别证券代码列",
            details={
                "source_file": source_file,
                "source_kind": source_kind,
                "candidate_fields": CODE_FIELD_CANDIDATES,
                "sample_headers": sorted({str(k) for row in rows[:10] for k in row.keys()}),
            },
        )

    normalized_rows: list[dict[str, Any]] = []
    normalized_codes: list[str] = []
    a_share_codes: list[str] = []
    non_a_codes: list[str] = []
    invalid_rows: list[dict[str, Any]] = []

    for index, row in enumerate(rows, start=1):
        raw_code = row.get(code_field)
        normalized = normalize_code(raw_code)
        classification = classify_code(normalized)
        record = {
            "row_index": index,
            "raw_code": json_safe(raw_code),
            "normalized_code": normalized,
            "classification": classification,
            "raw_row": json_safe(row),
        }
        normalized_rows.append(record)
        if not normalized:
            invalid_rows.append(record)
            continue
        normalized_codes.append(normalized)
        if len(normalized) == 6:
            a_share_codes.append(normalized)
        else:
            non_a_codes.append(normalized)

    return InputBundle(
        source_kind=source_kind,
        source_file=source_file,
        source_label=source_label,
        rows=normalized_rows,
        all_codes=dedupe(normalized_codes),
        a_share_codes=dedupe(a_share_codes),
        non_a_codes=dedupe(non_a_codes),
        invalid_rows=invalid_rows,
        selected_a_share_codes=[],
    )



def load_input_file(path: Path) -> InputBundle:
    if not path.exists():
        raise FusionReportError(
            "input_file_missing",
            "输入文件不存在",
            details={"input_file": str(path)},
        )

    suffix = path.suffix.lower()
    if suffix == ".json":
        payload = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(payload, list):
            if payload and isinstance(payload[0], dict):
                return build_bundle_from_rows(
                    [json_safe(item) for item in payload],
                    source_kind="json_list_rows",
                    source_file=str(path),
                    source_label=path.name,
                )
            return build_bundle_from_code_list(
                [json_safe(item) for item in payload],
                source_kind="json_list_codes",
                source_file=str(path),
                source_label=path.name,
            )
        if isinstance(payload, dict):
            for key in ["holdings", "positions", "rows", "data", "items"]:
                value = payload.get(key)
                if isinstance(value, list) and value:
                    if isinstance(value[0], dict):
                        return build_bundle_from_rows(
                            [json_safe(item) for item in value],
                            source_kind=f"json_{key}",
                            source_file=str(path),
                            source_label=path.name,
                        )
                    return build_bundle_from_code_list(
                        [json_safe(item) for item in value],
                        source_kind=f"json_{key}_codes",
                        source_file=str(path),
                        source_label=path.name,
                    )
            if isinstance(payload.get("codes"), list):
                return build_bundle_from_code_list(
                    [json_safe(item) for item in payload.get("codes") or []],
                    source_kind="json_codes_field",
                    source_file=str(path),
                    source_label=path.name,
                )
        raise FusionReportError(
            "input_json_unsupported",
            "JSON 输入格式不支持",
            details={"input_file": str(path), "top_level_type": type(payload).__name__},
        )

    if suffix == ".csv":
        with path.open("r", encoding="utf-8-sig", newline="") as handle:
            reader = csv.DictReader(handle)
            rows = [dict(row) for row in reader]
        if not rows:
            raise FusionReportError(
                "input_empty",
                "CSV 输入为空",
                details={"input_file": str(path)},
            )
        return build_bundle_from_rows(
            rows,
            source_kind="csv_rows",
            source_file=str(path),
            source_label=path.name,
        )

    if suffix in {".xlsx", ".xls"}:
        try:
            import pandas as pd  # type: ignore
        except Exception as exc:  # pragma: no cover - dependency guard
            raise FusionReportError(
                "excel_dependency_missing",
                "当前环境缺少 Excel 解析依赖，无法读取 .xlsx/.xls",
                details={"input_file": str(path), "error": str(exc)},
            ) from exc
        workbook = pd.read_excel(path, sheet_name=None)
        rows: list[dict[str, Any]] = []
        for sheet_name, frame in workbook.items():
            if frame is None or frame.empty:
                continue
            frame = frame.where(pd.notna(frame), None)
            for sheet_row_index, record in enumerate(frame.to_dict(orient="records"), start=1):
                row = {str(k): json_safe(v) for k, v in record.items()}
                row["__sheet__"] = sheet_name
                row["__sheet_row__"] = sheet_row_index
                rows.append(row)
        if not rows:
            raise FusionReportError(
                "input_empty",
                "Excel 输入为空",
                details={"input_file": str(path)},
            )
        return build_bundle_from_rows(
            rows,
            source_kind="excel_rows",
            source_file=str(path),
            source_label=path.name,
        )

    if suffix in {".txt", ".list"}:
        chunks = re.split(r"[\s,;]+", path.read_text(encoding="utf-8"))
        codes = [chunk for chunk in chunks if str(chunk).strip()]
        return build_bundle_from_code_list(
            codes,
            source_kind="text_codes",
            source_file=str(path),
            source_label=path.name,
        )

    raise FusionReportError(
        "input_file_unsupported",
        "不支持的输入文件类型",
        details={"input_file": str(path), "suffix": suffix},
    )



def autodiscover_input_file(output_dir: Path) -> tuple[Path, str]:
    for pattern, label in AUTODISCOVER_PATTERNS:
        found = latest_file(output_dir, pattern)
        if found:
            return found, label
    raise FusionReportError(
        "input_autodiscover_failed",
        "未找到可用持仓输入源",
        details={
            "output_dir": str(output_dir),
            "patterns": [pattern for pattern, _ in AUTODISCOVER_PATTERNS],
        },
    )



def resolve_input_bundle(args: argparse.Namespace, output_dir: Path) -> InputBundle:
    if args.codes.strip():
        bundle = build_bundle_from_code_list(
            [chunk for chunk in args.codes.split(",") if str(chunk).strip()],
            source_kind="inline_codes",
            source_file="--codes",
            source_label="inline_codes",
        )
    elif args.input_file:
        bundle = load_input_file(Path(args.input_file).expanduser().resolve())
    else:
        discovered_path, discovered_label = autodiscover_input_file(output_dir)
        bundle = load_input_file(discovered_path)
        bundle.source_label = discovered_label

    if not bundle.all_codes:
        raise FusionReportError(
            "input_no_normalized_codes",
            "输入中没有可归一化的证券代码，按 fail-closed 停止",
            details={
                "source_file": bundle.source_file,
                "source_kind": bundle.source_kind,
                "invalid_rows": len(bundle.invalid_rows),
            },
        )

    if not bundle.a_share_codes:
        raise FusionReportError(
            "input_no_a_share_codes",
            "输入中没有 6 位 A 股代码，按 fail-closed 停止",
            details={
                "source_file": bundle.source_file,
                "all_codes": bundle.all_codes,
                "non_a_codes": bundle.non_a_codes,
            },
        )

    selected = bundle.a_share_codes
    if args.limit and args.limit > 0:
        selected = selected[: args.limit]
        if not selected:
            raise FusionReportError(
                "selection_empty_after_limit",
                "limit 过滤后没有剩余 A 股代码，按 fail-closed 停止",
                details={"limit": args.limit, "a_share_codes": bundle.a_share_codes},
            )
    bundle.selected_a_share_codes = selected
    return bundle



def init_run_artifacts(output_dir: Path, report_prefix: str, run_id: str) -> RunArtifacts:
    run_dir = output_dir / f"{report_prefix}_runs" / run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    return RunArtifacts(
        run_id=run_id,
        run_dir=run_dir,
        input_snapshot_json=run_dir / "input_snapshot.json",
        input_snapshot_csv=run_dir / "input_snapshot.csv",
        report_md=run_dir / "report.md",
        summary_json=run_dir / "summary.json",
        run_summary_txt=run_dir / "run_summary.txt",
        legacy_report_md=output_dir / f"{report_prefix}_{run_id}.md",
        legacy_summary_json=output_dir / f"{report_prefix}_{run_id}.json",
        latest_report_md=output_dir / f"{report_prefix}_latest.md",
        latest_summary_json=output_dir / f"{report_prefix}_latest_summary.json",
        latest_run_summary_txt=output_dir / f"{report_prefix}_latest_run_summary.txt",
        latest_input_snapshot_json=output_dir / f"{report_prefix}_latest_input_snapshot.json",
        latest_input_snapshot_csv=output_dir / f"{report_prefix}_latest_input_snapshot.csv",
    )



def write_input_snapshots(bundle: InputBundle, artifacts: RunArtifacts) -> None:
    selected_set = set(bundle.selected_a_share_codes)
    snapshot_payload = {
        "snapshot_generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "source_kind": bundle.source_kind,
        "source_label": bundle.source_label,
        "source_file": bundle.source_file,
        "stats": {
            "normalized_code_count": len(bundle.all_codes),
            "a_share_code_count": len(bundle.a_share_codes),
            "selected_a_share_code_count": len(bundle.selected_a_share_codes),
            "non_a_code_count": len(bundle.non_a_codes),
            "invalid_row_count": len(bundle.invalid_rows),
        },
        "all_codes": bundle.all_codes,
        "a_share_codes": bundle.a_share_codes,
        "selected_a_share_codes": bundle.selected_a_share_codes,
        "non_a_codes": bundle.non_a_codes,
        "invalid_rows": bundle.invalid_rows,
        "rows": [
            {
                **row,
                "selected_for_a_share_report": str(row.get("normalized_code") or "") in selected_set,
            }
            for row in bundle.rows
        ],
    }
    artifacts.input_snapshot_json.write_text(
        json.dumps(snapshot_payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    with artifacts.input_snapshot_csv.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=[
                "row_index",
                "raw_code",
                "normalized_code",
                "classification",
                "selected_for_a_share_report",
                "source_kind",
                "source_file",
            ],
        )
        writer.writeheader()
        for row in bundle.rows:
            writer.writerow(
                {
                    "row_index": row.get("row_index"),
                    "raw_code": row.get("raw_code"),
                    "normalized_code": row.get("normalized_code") or "",
                    "classification": row.get("classification"),
                    "selected_for_a_share_report": str(row.get("normalized_code") or "") in selected_set,
                    "source_kind": bundle.source_kind,
                    "source_file": bundle.source_file,
                }
            )



def sync_stock_daily_config(codes_6d: list[str], output_dir: Path) -> None:
    STOCK_DAILY_DIR.mkdir(parents=True, exist_ok=True)
    cfg: dict[str, Any] = {}
    if STOCK_DAILY_CONFIG.exists():
        try:
            cfg = json.loads(STOCK_DAILY_CONFIG.read_text(encoding="utf-8"))
        except Exception:
            cfg = {}

    cfg["stocks"] = [{"code": code, "name": code} for code in codes_6d]
    cfg.setdefault("report_prefix", "stock-daily-report")
    cfg.setdefault("output_format", "both")
    cfg["output_dir"] = str(output_dir)
    STOCK_DAILY_CONFIG.write_text(json.dumps(cfg, ensure_ascii=False, indent=2), encoding="utf-8")



def sync_stock_watcher_watchlist(codes: list[str]) -> None:
    STOCK_WATCHER_WATCHLIST.parent.mkdir(parents=True, exist_ok=True)
    lines = [f"{code}|{code}" for code in codes]
    STOCK_WATCHER_WATCHLIST.write_text("\n".join(lines) + "\n", encoding="utf-8")



def run_cmd(cmd: list[str], cwd: Path | None = None, timeout: int = 300) -> tuple[int, str, str]:
    try:
        proc = subprocess.run(
            cmd,
            cwd=str(cwd) if cwd else None,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        return proc.returncode, proc.stdout or "", proc.stderr or ""
    except subprocess.TimeoutExpired as exc:
        return 124, exc.stdout or "", f"timeout after {timeout}s\n{exc.stderr or ''}".strip()
    except FileNotFoundError as exc:
        return 127, "", str(exc)



def run_stock_daily_report(codes_6d: list[str], output_dir: Path, run_id: str) -> dict[str, Any]:
    if not codes_6d:
        return {"ok": False, "reason": "no_6digit_a_share_codes"}
    if not STOCK_DAILY_ENTRY.exists():
        return {
            "ok": False,
            "reason": "stock_daily_report_missing",
            "entry": str(STOCK_DAILY_ENTRY),
        }

    output_base = output_dir / f"stock-daily-report_{run_id}"
    cmd = [
        "python3",
        str(STOCK_DAILY_ENTRY),
        "--stocks",
        ",".join(codes_6d),
        "--format",
        "both",
        "--output",
        str(output_base),
    ]
    rc, out, err = run_cmd(cmd, timeout=900)
    html_file = Path(str(output_base) + ".html")
    image_file = Path(str(output_base) + ".png")
    return {
        "ok": rc == 0 and html_file.exists(),
        "returncode": rc,
        "command": cmd,
        "stdout_tail": safe_tail(out),
        "stderr_tail": safe_tail(err),
        "html_file": str(html_file) if html_file.exists() else "",
        "image_file": str(image_file) if image_file.exists() else "",
    }



def run_stock_watcher_summary() -> dict[str, Any]:
    if not STOCK_WATCHER_SUMMARY.exists():
        return {"ok": False, "reason": "stock_watcher_not_installed"}

    rc, out, err = run_cmd(["python3", str(STOCK_WATCHER_SUMMARY)], timeout=240)
    lines = [line for line in out.splitlines() if line.strip()]
    return {
        "ok": rc == 0 and len(lines) > 0,
        "returncode": rc,
        "command": ["python3", str(STOCK_WATCHER_SUMMARY)],
        "lines": lines[:120],
        "stderr_tail": safe_tail(err),
    }



def fetch_akshare_flow(code: str) -> dict[str, Any] | None:
    if not AKSHARE_STOCK_CLI.exists():
        return None
    rc, out, err = run_cmd(["python3", str(AKSHARE_STOCK_CLI), "flow", "--symbol", code], timeout=120)
    if rc != 0:
        return {
            "code": code,
            "error": safe_tail(err) or f"returncode={rc}",
        }
    try:
        rows = json.loads(out)
    except Exception:
        return {"code": code, "error": "invalid_json_response"}
    if not isinstance(rows, list) or not rows:
        return {"code": code, "error": "empty_flow_rows"}
    row = rows[0]
    return {
        "code": code,
        "date": row.get("日期"),
        "close": row.get("收盘价"),
        "pct": row.get("涨跌幅"),
        "main_inflow": row.get("主力净流入-净额"),
        "main_inflow_ratio": row.get("主力净流入-净占比"),
    }



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
    info = (out.strip() or err.strip())[-1000:]
    return rc == 0, info



def build_markdown(summary: dict[str, Any]) -> str:
    input_info = summary.get("input", {})
    stock_daily = summary.get("stock_daily", {})
    watcher = summary.get("stock_watcher", {})
    flow_rows = summary.get("akshare_flow_rows", []) or []
    artifacts = summary.get("artifacts", {})

    lines = [
        f"# A-Share Fusion Report ({summary.get('generated_at')})",
        "",
        "## Run Status",
        f"- Status: **{summary.get('status')}**",
        f"- Run ID: `{summary.get('run_id')}`",
        f"- Output dir: `{summary.get('output_dir')}`",
        f"- Degraded reasons: `{', '.join(summary.get('degraded_reasons') or ['none'])}`",
        "",
        "## Input",
        f"- Source label: `{input_info.get('source_label', '-')}`",
        f"- Source file: `{input_info.get('source_file', '-')}`",
        f"- Source kind: `{input_info.get('source_kind', '-')}`",
        f"- Normalized codes: **{input_info.get('normalized_code_count', 0)}**",
        f"- A-share codes: **{input_info.get('a_share_code_count', 0)}**",
        f"- Selected A-share codes: **{input_info.get('selected_a_share_code_count', 0)}**",
        f"- Non A-share codes: `{', '.join(input_info.get('non_a_codes') or []) or '-'}`",
        f"- Invalid rows: **{input_info.get('invalid_row_count', 0)}**",
        "",
        "## Input Snapshots",
        f"- JSON: `{artifacts.get('input_snapshot_json', '-')}`",
        f"- CSV: `{artifacts.get('input_snapshot_csv', '-')}`",
        f"- Latest JSON: `{artifacts.get('latest_input_snapshot_json', '-')}`",
        f"- Latest CSV: `{artifacts.get('latest_input_snapshot_csv', '-')}`",
        "",
        "## Report Engine (stock-daily-report)",
        f"- Status: **{'OK' if stock_daily.get('ok') else 'FAILED'}**",
        f"- HTML: `{stock_daily.get('html_file') or '-'}`",
        f"- Image: `{stock_daily.get('image_file') or '-'}`",
    ]
    if stock_daily.get("stderr_tail"):
        lines.append(f"- stderr tail: `{stock_daily.get('stderr_tail')}`")

    lines += [
        "",
        "## Fast Quotes Fallback (stock-watcher)",
        f"- Status: **{'OK' if watcher.get('ok') else 'FAILED'}**",
    ]
    for line in (watcher.get("lines") or [])[:15]:
        lines.append(f"- {line}")
    if watcher.get("stderr_tail"):
        lines.append(f"- stderr tail: `{watcher.get('stderr_tail')}`")

    lines += ["", "## Professional Overlay (akshare fund flow)"]
    valid_flow_rows = [row for row in flow_rows if not row.get("error")]
    failed_flow_rows = [row for row in flow_rows if row.get("error")]
    if valid_flow_rows:
        lines += [
            "",
            "| code | date | close | pct | main_inflow | main_inflow_ratio |",
            "|---|---|---:|---:|---:|---:|",
        ]
        for row in valid_flow_rows:
            lines.append(
                f"| {row.get('code')} | {row.get('date')} | {row.get('close')} | {row.get('pct')} | {row.get('main_inflow')} | {row.get('main_inflow_ratio')} |"
            )
    else:
        lines.append("- 暂无可用资金流数据（网络/接口限制）。")
    if failed_flow_rows:
        lines.append("")
        lines.append("### Flow Errors")
        for row in failed_flow_rows[:10]:
            lines.append(f"- {row.get('code')}: `{row.get('error')}`")

    lines += [
        "",
        "## Stable Artifacts",
        f"- Summary JSON: `{artifacts.get('summary_json', '-')}`",
        f"- Markdown report: `{artifacts.get('report_md', '-')}`",
        f"- Run summary: `{artifacts.get('run_summary_txt', '-')}`",
        f"- Latest summary JSON: `{artifacts.get('latest_summary_json', '-')}`",
        f"- Latest markdown report: `{artifacts.get('latest_report_md', '-')}`",
        f"- Latest run summary: `{artifacts.get('latest_run_summary_txt', '-')}`",
    ]
    return "\n".join(lines)



def build_run_summary_text(summary: dict[str, Any]) -> str:
    input_info = summary.get("input", {})
    lines = [
        f"status={summary.get('status')}",
        f"run_id={summary.get('run_id')}",
        f"generated_at={summary.get('generated_at')}",
        f"source_file={input_info.get('source_file', '-')}",
        f"selected_a_share_codes={','.join(input_info.get('selected_a_share_codes') or [])}",
        f"degraded_reasons={','.join(summary.get('degraded_reasons') or ['none'])}",
        f"report_md={summary.get('artifacts', {}).get('report_md', '-')}",
        f"summary_json={summary.get('artifacts', {}).get('summary_json', '-')}",
        f"run_summary_txt={summary.get('artifacts', {}).get('run_summary_txt', '-')}",
    ]
    return "\n".join(lines) + "\n"



def publish_artifacts(artifacts: RunArtifacts) -> None:
    shutil.copyfile(artifacts.report_md, artifacts.legacy_report_md)
    shutil.copyfile(artifacts.summary_json, artifacts.legacy_summary_json)
    shutil.copyfile(artifacts.report_md, artifacts.latest_report_md)
    shutil.copyfile(artifacts.summary_json, artifacts.latest_summary_json)
    shutil.copyfile(artifacts.run_summary_txt, artifacts.latest_run_summary_txt)
    shutil.copyfile(artifacts.input_snapshot_json, artifacts.latest_input_snapshot_json)
    shutil.copyfile(artifacts.input_snapshot_csv, artifacts.latest_input_snapshot_csv)



def make_run_id() -> str:
    return datetime.now().strftime("%Y%m%d_%H%M%S_%f")



def main() -> None:
    parser = argparse.ArgumentParser(description="Fuse stock-watcher + akshare-stock + stock-daily-report")
    source_group = parser.add_mutually_exclusive_group()
    source_group.add_argument("--codes", default="", help="Override codes, comma-separated")
    source_group.add_argument("--input-file", default="", help="Explicit input file: json/csv/xlsx/xls/txt")
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
    run_id = make_run_id()
    artifacts = init_run_artifacts(output_dir, args.report_prefix, run_id)

    try:
        bundle = resolve_input_bundle(args, output_dir)
        write_input_snapshots(bundle, artifacts)

        sync_stock_daily_config(bundle.selected_a_share_codes, output_dir)
        sync_stock_watcher_watchlist(bundle.all_codes)

        stock_daily = run_stock_daily_report(bundle.selected_a_share_codes, output_dir, run_id)
        watcher = run_stock_watcher_summary()
        if not stock_daily.get("ok") and not watcher.get("ok"):
            raise FusionReportError(
                "all_report_engines_failed",
                "stock-daily-report 与 stock-watcher 同时失败，按 fail-closed 停止",
                details={
                    "stock_daily": stock_daily,
                    "stock_watcher": {
                        "ok": watcher.get("ok"),
                        "returncode": watcher.get("returncode"),
                        "stderr_tail": watcher.get("stderr_tail"),
                    },
                },
            )

        flow_rows: list[dict[str, Any]] = []
        for code in bundle.selected_a_share_codes[: max(0, args.akshare_top)]:
            row = fetch_akshare_flow(code)
            if row:
                flow_rows.append(row)

        degraded_reasons: list[str] = []
        if not stock_daily.get("ok"):
            degraded_reasons.append("stock_daily_report_failed")
        if any(row.get("error") for row in flow_rows):
            degraded_reasons.append("partial_akshare_flow_failure")

        status = "SUCCESS" if not degraded_reasons else "SUCCESS_WITH_FALLBACK"
        summary = {
            "status": status,
            "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "run_id": run_id,
            "output_dir": str(output_dir),
            "degraded_reasons": degraded_reasons,
            "input": {
                "source_kind": bundle.source_kind,
                "source_label": bundle.source_label,
                "source_file": bundle.source_file,
                "normalized_code_count": len(bundle.all_codes),
                "a_share_code_count": len(bundle.a_share_codes),
                "selected_a_share_code_count": len(bundle.selected_a_share_codes),
                "non_a_codes": bundle.non_a_codes,
                "invalid_row_count": len(bundle.invalid_rows),
                "all_codes": bundle.all_codes,
                "selected_a_share_codes": bundle.selected_a_share_codes,
            },
            "stock_daily": stock_daily,
            "stock_watcher": {
                "ok": watcher.get("ok", False),
                "returncode": watcher.get("returncode"),
                "lines": (watcher.get("lines") or [])[:20],
                "stderr_tail": watcher.get("stderr_tail"),
            },
            "akshare_flow_rows": flow_rows,
            "artifacts": {
                "run_dir": str(artifacts.run_dir),
                "input_snapshot_json": str(artifacts.input_snapshot_json),
                "input_snapshot_csv": str(artifacts.input_snapshot_csv),
                "report_md": str(artifacts.report_md),
                "summary_json": str(artifacts.summary_json),
                "run_summary_txt": str(artifacts.run_summary_txt),
                "legacy_report_md": str(artifacts.legacy_report_md),
                "legacy_summary_json": str(artifacts.legacy_summary_json),
                "latest_report_md": str(artifacts.latest_report_md),
                "latest_summary_json": str(artifacts.latest_summary_json),
                "latest_run_summary_txt": str(artifacts.latest_run_summary_txt),
                "latest_input_snapshot_json": str(artifacts.latest_input_snapshot_json),
                "latest_input_snapshot_csv": str(artifacts.latest_input_snapshot_csv),
            },
        }

        artifacts.report_md.write_text(build_markdown(summary), encoding="utf-8")
        artifacts.run_summary_txt.write_text(build_run_summary_text(summary), encoding="utf-8")
        artifacts.summary_json.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
        publish_artifacts(artifacts)

        if args.push_feishu:
            msg = (
                "📈 A股融合报告已生成\n"
                f"- 状态: {summary['status']}\n"
                f"- A股代码数: {len(bundle.selected_a_share_codes)}\n"
                f"- MD: {artifacts.report_md}\n"
                f"- Summary: {artifacts.summary_json}"
            )
            ok, info = push_to_feishu(
                target_user=args.target_user,
                message=msg,
                image_file=stock_daily.get("image_file", ""),
            )
            summary["feishu_push"] = {"ok": ok, "info": info}
            artifacts.summary_json.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
            publish_artifacts(artifacts)

        print(json.dumps(summary, ensure_ascii=False, indent=2))
    except FusionReportError as exc:
        failure = {
            "status": "FAILED_CLOSED",
            "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "run_id": run_id,
            "output_dir": str(output_dir),
            "error": exc.to_payload(),
            "artifacts": {
                "run_dir": str(artifacts.run_dir),
                "summary_json": str(artifacts.summary_json),
                "run_summary_txt": str(artifacts.run_summary_txt),
            },
        }
        artifacts.summary_json.write_text(json.dumps(failure, ensure_ascii=False, indent=2), encoding="utf-8")
        artifacts.run_summary_txt.write_text(
            f"status=FAILED_CLOSED\nrun_id={run_id}\nerror_code={exc.code}\nerror_message={exc.message}\n",
            encoding="utf-8",
        )
        print(json.dumps(failure, ensure_ascii=False, indent=2))
        sys.exit(exc.exit_code)
    except Exception as exc:  # pragma: no cover - defensive guard
        failure = {
            "status": "FAILED_EXCEPTION",
            "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "run_id": run_id,
            "output_dir": str(output_dir),
            "error": {
                "code": "unexpected_exception",
                "message": str(exc),
                "type": type(exc).__name__,
            },
            "artifacts": {
                "run_dir": str(artifacts.run_dir),
                "summary_json": str(artifacts.summary_json),
                "run_summary_txt": str(artifacts.run_summary_txt),
            },
        }
        artifacts.summary_json.write_text(json.dumps(failure, ensure_ascii=False, indent=2), encoding="utf-8")
        artifacts.run_summary_txt.write_text(
            f"status=FAILED_EXCEPTION\nrun_id={run_id}\nerror_type={type(exc).__name__}\nerror_message={exc}\n",
            encoding="utf-8",
        )
        print(json.dumps(failure, ensure_ascii=False, indent=2))
        sys.exit(3)


if __name__ == "__main__":
    main()

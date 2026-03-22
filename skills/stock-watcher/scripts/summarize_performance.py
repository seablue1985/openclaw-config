#!/usr/bin/env python3
"""
Summarize watchlist performance with structured quote parsing.
Data source: Sina quote API (hq.sinajs.cn), with deterministic fields.
"""
import os
import sys
import time
import requests
import urllib3

# 避免代理/证书环境下的 verify=False 警告刷屏
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

WATCHLIST_FILE = os.path.expanduser("~/.clawdbot/stock_watcher/watchlist.txt")


def _to_symbol(code: str) -> str:
    code = str(code).strip()
    if code.startswith(("6", "9", "5")):
        return f"sh{code}"
    return f"sz{code}"


def fetch_stock_data(stock_code: str):
    """Fetch stock quote from Sina with structured parsing."""
    symbol = _to_symbol(stock_code)
    url = f"http://hq.sinajs.cn/list={symbol}"

    try:
        headers = {
            "User-Agent": "Mozilla/5.0",
            "Referer": "https://finance.sina.com.cn",
        }
        resp = requests.get(url, headers=headers, timeout=10, verify=False)
        if resp.status_code != 200:
            return None

        text = resp.content.decode("gbk", errors="ignore").strip()
        # var hq_str_sh600519="贵州茅台,1395.000,1399.040,1402.000,...";
        if "\"" not in text:
            return None
        body = text.split("\"", 1)[1].rsplit("\"", 1)[0]
        parts = body.split(",")
        if len(parts) < 4:
            return None

        name = parts[0].strip() or stock_code
        prev_close = float(parts[2]) if parts[2] else 0.0
        current = float(parts[3]) if parts[3] else 0.0
        change = current - prev_close
        pct = (change / prev_close * 100.0) if prev_close else 0.0

        return {
            "code": stock_code,
            "name": name,
            "current": current,
            "prev_close": prev_close,
            "change": change,
            "pct": pct,
            "url": f"https://stockpage.10jqka.com.cn/{stock_code}/",
        }
    except Exception as e:
        print(f"Error fetching data for {stock_code}: {e}", file=sys.stderr)
        return None


def summarize_performance():
    if not os.path.exists(WATCHLIST_FILE):
        return

    with open(WATCHLIST_FILE, "r", encoding="utf-8") as f:
        lines = [ln.strip() for ln in f.readlines() if ln.strip()]

    if not lines:
        return

    for line in lines:
        parts = line.split("|", 1)
        if len(parts) != 2:
            continue
        code, watch_name = parts

        stock_data = fetch_stock_data(code)
        if stock_data:
            name = stock_data.get("name") or watch_name
            current = stock_data.get("current", 0.0)
            pct = stock_data.get("pct", 0.0)
            change = stock_data.get("change", 0.0)
            print(f"{code} - {name} - 现价:{current:.2f} 涨跌:{change:+.2f} 涨跌幅:{pct:+.2f}%")
        else:
            print(f"{code} - {watch_name} - 获取数据失败")

        # respect public quote endpoint
        time.sleep(0.5)


if __name__ == "__main__":
    summarize_performance()

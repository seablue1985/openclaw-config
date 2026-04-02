#!/usr/bin/env python3
from __future__ import annotations
"""
Weibo Monitor V2 - 监测 + 内容分析 + 评论情绪汇总
功能：
  1. 监控指定博主新微博
  2. 抓取评论并做情绪分析
  3. 生成内容摘要和评论总结
  4. 推送完整报告到飞书
"""

import json
import re
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

import requests

# 加载配置
BASE_DIR = Path(__file__).parent.parent
COOKIE_FILE = BASE_DIR / "config" / "cookie.env"
WATCHLIST_FILE = BASE_DIR / "config" / "watchlist.json"
STATE_DIR = BASE_DIR / "state"
STATE_DIR.mkdir(exist_ok=True)
LAST_ID_FILE = STATE_DIR / "last_post_id.json"

FEISHU_WEBHOOK = "https://open.feishu.cn/open-apis/bot/v2/hook/f54d31a7-226d-4fac-aeaf-44b84c5c85b7"

DEFAULT_WATCHLIST = [
    {"uid": "2014433131", "name": "股票博主"},
]

STOCK_KEYWORDS = [
    "股票", "A股", "大盘", "上证", "深证", "指数", "涨跌", "涨停", "跌停", "持仓",
    "建仓", "清仓", "加仓", "减仓", "牛市", "熊市", "回调", "反弹", "突破", "支撑",
    "压力", "板块", "概念", "龙头", "主力", "资金", "量能", "缩量", "放量",
    "研报", "业绩", "财报", "期权", "期货", "融资", "美股", "港股", "汇率", "油价",
    "新能源", "半导体", "芯片", "AI", "医药", "证券", "基金", "量化", "央行", "美联储",
]


def ensure_default_watchlist_file() -> None:
    WATCHLIST_FILE.parent.mkdir(parents=True, exist_ok=True)
    if WATCHLIST_FILE.exists():
        return
    WATCHLIST_FILE.write_text(
        json.dumps(DEFAULT_WATCHLIST, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def load_watchlist() -> list[dict[str, str]]:
    ensure_default_watchlist_file()
    try:
        raw = json.loads(WATCHLIST_FILE.read_text(encoding="utf-8"))
    except Exception as exc:
        raise RuntimeError(f"watchlist 配置读取失败: {exc}") from exc

    if not isinstance(raw, list):
        raise RuntimeError("watchlist.json 格式错误：顶层必须是数组")

    normalized: list[dict[str, str]] = []
    seen: set[str] = set()
    for idx, item in enumerate(raw, start=1):
        if not isinstance(item, dict):
            raise RuntimeError(f"watchlist.json 第 {idx} 项格式错误：必须是对象")
        uid = str(item.get("uid", "")).strip()
        name = str(item.get("name", "")).strip() or f"博主{idx}"
        if not uid:
            raise RuntimeError(f"watchlist.json 第 {idx} 项缺少 uid")
        if uid in seen:
            continue
        seen.add(uid)
        normalized.append({"uid": uid, "name": name})

    if not normalized:
        raise RuntimeError("watchlist.json 为空：请至少配置 1 个博主")
    return normalized


def load_cookie() -> Optional[str]:
    env = COOKIE_FILE.read_text(encoding="utf-8")
    for line in env.splitlines():
        if line.startswith("WEIBO_COOKIE="):
            return line.split("=", 1)[1].strip().strip('"')
    return None


def fetch_posts(uid: str, cookie: str, page: int = 1) -> list[dict[str, Any]]:
    """获取博主最新微博"""
    headers = {
        "User-Agent": "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Mobile/15E148 Safari/604.1",
        "Cookie": cookie,
        "Accept": "application/json",
        "Referer": f"https://weibo.com/u/{uid}",
    }
    url = "https://weibo.com/ajax/statuses/mymblog"
    params = {"uid": uid, "page": page, "feature": 0, "lang": "zh-CN"}
    resp = requests.get(url, params=params, headers=headers, timeout=10)
    resp.raise_for_status()
    data = resp.json()
    if data.get("ok") == -100:
        raise RuntimeError(f"微博 Cookie 已失效，需要重新登录: uid={uid}")
    return data.get("data", {}).get("list", []) or []


def fetch_comments(post_id: str, cookie: str, max_pages: int = 3) -> list[dict[str, Any]]:
    """获取微博评论"""
    headers = {
        "User-Agent": "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit/605.1.15",
        "Cookie": cookie,
        "Accept": "application/json",
        "Referer": "https://weibo.com",
    }
    all_comments: list[dict[str, Any]] = []
    for page in range(1, max_pages + 1):
        try:
            url = "https://m.weibo.cn/api/comments/show"
            params = {"id": post_id, "page": page}
            resp = requests.get(url, params=params, headers=headers, timeout=10)
            if resp.status_code != 200:
                break
            data = resp.json()
            comments = data.get("data", {}).get("data") or []
            if not comments:
                break
            import html as html_module

            for comment in comments:
                raw = comment.get("text", "") or ""
                text = html_module.unescape(re.sub(r"<[^>]+>", "", str(raw))).strip()
                if text:
                    all_comments.append(
                        {
                            "text": text,
                            "like": comment.get("like_counts", 0),
                            "user": comment.get("user", {}).get("screen_name", "匿名"),
                        }
                    )
        except Exception:
            break
    return all_comments


def clean_text(html_text: str) -> str:
    """清理HTML，保留纯文本"""
    import html as html_module

    text = re.sub(r"<[^>]+>", "", str(html_text))
    text = html_module.unescape(text)
    text = text.replace("&nbsp;", " ").replace("&amp;", "&")
    text = text.replace("&lt;", "<").replace("&gt;", ">").replace("&#10;", "\n")
    return text.strip()


def is_stock_related(text: str) -> int:
    """判断是否股票相关内容"""
    return sum(1 for kw in STOCK_KEYWORDS if kw in text)


def analyze_sentiment(comments: list[dict[str, Any]]) -> tuple[str, int, int, int]:
    """简单情绪分析（基于关键词）"""
    positive = ["加油", "支持", "点赞", "厉害", "牛", "强", "好", "对", "稳", "涨"]
    negative = ["亏", "跌", "傻", "骗", "垃圾", "恶心", "跌了", "完了", "危险", "割"]

    pos_count = sum(1 for c in comments for w in positive if w in c["text"])
    neg_count = sum(1 for c in comments for w in negative if w in c["text"])

    total = len(comments)
    if total == 0:
        return "无评论", 0, 0, 0

    pos_ratio = pos_count / total
    neg_ratio = neg_count / total

    if pos_ratio > neg_ratio * 2:
        sentiment = "偏正面 👍"
    elif neg_ratio > pos_ratio * 2:
        sentiment = "偏负面 👎"
    elif pos_ratio > 0.3:
        sentiment = "中性偏正面"
    elif neg_ratio > 0.3:
        sentiment = "中性偏负面"
    else:
        sentiment = "中性"

    return sentiment, pos_count, neg_count, total


def build_summary(comments: list[dict[str, Any]]) -> str:
    """生成评论摘要"""
    if not comments:
        return "暂无评论"

    top_comments = sorted(comments, key=lambda x: x["like"], reverse=True)[:5]
    lines = []
    for i, comment in enumerate(top_comments, 1):
        text = comment["text"][:80] + ("..." if len(comment["text"]) > 80 else "")
        lines.append(f"{i}. {text} (👍{comment['like']})")
    return "\n".join(lines)


def extract_meaningful_text(text: str) -> str:
    """去掉话题/提及/链接等壳子，提取真正有信息量的正文"""
    cleaned = re.sub(r"https?://\S+", " ", text)
    cleaned = re.sub(r"#([^#]+)#", " ", cleaned)
    cleaned = re.sub(r"@[^\s:：]+", " ", cleaned)
    cleaned = re.sub(r"\[[^\]]+\]", " ", cleaned)
    cleaned = re.sub(r"\s+", " ", cleaned)
    return cleaned.strip(" 　\n\t-—:：;；,，.。!！?？()（）[]【】/\\|+").strip()


def is_low_signal_post(text: str, comment_total: int) -> bool:
    """过滤低信息量微博：正文几乎只剩标签/符号，且没有评论互动。"""
    if comment_total > 0:
        return False
    meaningful = extract_meaningful_text(text)
    compact = re.sub(r"\s+", "", meaningful)
    return len(compact) <= 8


def send_feishu(msg: str) -> dict[str, Any]:
    """发送飞书消息"""
    payload = {"msg_type": "text", "content": {"text": msg}}
    resp = requests.post(FEISHU_WEBHOOK, json=payload, timeout=10)
    return resp.json()


def load_last_ids() -> dict[str, str]:
    if LAST_ID_FILE.exists():
        return json.loads(LAST_ID_FILE.read_text(encoding="utf-8"))
    return {}


def save_last_ids(ids: dict[str, str]) -> None:
    LAST_ID_FILE.write_text(json.dumps(ids, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def main() -> None:
    cookie = load_cookie()
    if not cookie:
        print("错误: 未找到微博 Cookie")
        sys.exit(1)

    try:
        watchlist = load_watchlist()
    except Exception as exc:
        print(f"错误: {exc}")
        sys.exit(1)

    print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] 开始检测微博...")
    print(f"监控博主数: {len(watchlist)}")

    last_ids = load_last_ids()
    all_new_posts: list[dict[str, Any]] = []
    had_fetch_error = False

    for blogger in watchlist:
        uid = blogger["uid"]
        name = blogger["name"]

        try:
            posts = fetch_posts(uid, cookie)
        except Exception as exc:
            had_fetch_error = True
            print(f"获取微博失败 {uid} ({name}): {exc}")
            continue

        if not posts:
            print(f"未获取到微博 UID={uid} ({name})")
            continue

        effective_posts = [post for post in posts if not post.get("isTop")]
        if not effective_posts:
            print(f"未获取到非置顶微博 UID={uid} ({name})")
            continue

        new_posts: list[dict[str, Any]] = []
        last_known = last_ids.get(uid)
        last_known_is_top = any(str(post.get("idstr", "")) == last_known and post.get("isTop") for post in posts)

        if last_known_is_top:
            print(f"  {name}: 检测到旧状态命中了置顶帖，切换为非置顶微博基线")
            today_token = datetime.now().strftime("%a %b %d")
            for post in effective_posts:
                created_at = str(post.get("created_at", ""))
                if created_at.startswith(today_token):
                    new_posts.append(post)
                else:
                    break
        else:
            for post in effective_posts:
                post_id = str(post.get("idstr", ""))
                if post_id == last_known:
                    break
                new_posts.append(post)

        if new_posts:
            latest = effective_posts[0]
            last_ids[uid] = str(latest.get("idstr", ""))
            print(f"  {name}: 发现 {len(new_posts)} 条新微博")
            for post in reversed(new_posts):
                all_new_posts.append({"uid": uid, "name": name, "post": post})

    if not all_new_posts:
        if had_fetch_error:
            print("本轮抓取失败，未进入新微博检测")
            sys.exit(1)
        print("没有新微博")
        return

    save_last_ids(last_ids)

    for item in all_new_posts:
        uid = item["uid"]
        name = item["name"]
        post = item["post"]

        post_id = str(post.get("idstr", ""))
        post_text = clean_text(post.get("text_raw", post.get("text", "")))
        post_url = f"https://weibo.com/{uid}/{post_id}"

        print(f"\n分析 [{name}]: {post_text[:50]}...")

        comments = fetch_comments(post_id, cookie, max_pages=5)
        print(f"  获取到 {len(comments)} 条评论")

        sentiment, pos, neg, total = analyze_sentiment(comments)
        if is_low_signal_post(post_text, total):
            print("  跳过低信息量微博：正文过短/仅标签，且暂无评论")
            continue
        comment_summary = build_summary(comments)

        short_text = post_text[:200] + ("..." if len(post_text) > 200 else "")
        msg = f"""📢 【{name}】新发微博（股票相关）

📝 内容：
{short_text}

💬 评论分析（{total}条）
情绪：{sentiment}
正向词命中：{pos}
负向词命中：{neg}
👥 高赞评论：
{comment_summary}

🔗 {post_url}"""

        print("\n发送飞书通知...")
        result = send_feishu(msg)
        print(f"  发送结果: {result.get('msg', result)}")


if __name__ == "__main__":
    main()

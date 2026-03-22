#!/usr/bin/env python3
"""
Weibo Monitor V2 - 监测 + 内容分析 + 评论情绪汇总
功能：
  1. 监控指定博主新微博
  2. 抓取评论并做情绪分析
  3. LLM 生成内容摘要和评论总结
  4. 推送完整报告到飞书
"""

import json
import os
import sys
import re
import requests
from datetime import datetime
from pathlib import Path

# 加载配置
COOKIE_FILE = Path(__file__).parent.parent / "config" / "cookie.env"
STATE_DIR = Path(__file__).parent.parent / "state"
STATE_DIR.mkdir(exist_ok=True)
LAST_ID_FILE = STATE_DIR / "last_post_id.json"

FEISHU_WEBHOOK = "https://open.feishu.cn/open-apis/bot/v2/hook/f54d31a7-226d-4fac-aeaf-44b84c5c85b7"

# 博主列表
WATCHLIST = [
    {"uid": "2014433131", "name": "股票博主"},
]

STOCK_KEYWORDS = [
    "股票","A股","大盘","上证","深证","指数","涨跌","涨停","跌停","持仓",
    "建仓","清仓","加仓","减仓","牛市","熊市","回调","反弹","突破","支撑",
    "压力","板块","概念","龙头","主力","资金","量能","缩量","放量",
    "研报","业绩","财报","期权","期货","融资","美股","港股","汇率","油价",
    "新能源","半导体","芯片","AI","医药","证券","基金","量化","央行","美联储",
]


def load_cookie():
    env = COOKIE_FILE.read_text()
    for line in env.splitlines():
        if line.startswith("WEIBO_COOKIE="):
            return line.split("=", 1)[1].strip().strip('"')
    return None


def fetch_posts(uid, cookie, page=1):
    """获取博主最新微博"""
    headers = {
        "User-Agent": "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Mobile/15E148 Safari/604.1",
        "Cookie": cookie,
        "Accept": "application/json",
        "Referer": f"https://weibo.com/u/{uid}",
    }
    url = f"https://weibo.com/ajax/statuses/mymblog"
    params = {"uid": uid, "page": page, "feature": 0, "lang": "zh-CN"}
    resp = requests.get(url, params=params, headers=headers, timeout=10)
    resp.raise_for_status()
    return resp.json().get("data", {}).get("list", [])


def fetch_comments(post_id, cookie, max_pages=3):
    """获取微博评论"""
    headers = {
        "User-Agent": "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit/605.1.15",
        "Cookie": cookie,
        "Accept": "application/json",
        "Referer": "https://weibo.com",
    }
    all_comments = []
    for page in range(1, max_pages + 1):
        try:
            url = f"https://m.weibo.cn/api/comments/show"
            params = {"id": post_id, "page": page}
            resp = requests.get(url, params=params, headers=headers, timeout=10)
            if resp.status_code != 200:
                break
            data = resp.json()
            comments = data.get("data", {}).get("data") or []
            if not comments:
                break
            import html as html_module
            for c in comments:
                raw = c.get("text", "") or ""
                text = html_module.unescape(re.sub(r"<[^>]+>", "", str(raw))).strip()
                if text:
                    all_comments.append({
                        "text": text,
                        "like": c.get("like_counts", 0),
                        "user": c.get("user", {}).get("screen_name", "匿名"),
                    })
        except Exception:
            break
    return all_comments


def clean_text(html_text):
    """清理HTML，保留纯文本"""
    import html as html_module
    text = re.sub(r"<[^>]+>", "", str(html_text))
    text = html_module.unescape(text)
    text = text.replace("&nbsp;", " ").replace("&amp;", "&")
    text = text.replace("&lt;", "<").replace("&gt;", ">").replace("&#10;", "\n")
    return text.strip()


def is_stock_related(text):
    """判断是否股票相关内容"""
    return sum(1 for kw in STOCK_KEYWORDS if kw in text)


def analyze_sentiment(comments):
    """简单情绪分析（基于关键词）"""
    positive = ["加油","支持","点赞","厉害","牛","强","好","对","稳","涨"]
    negative = ["亏","跌","傻","骗","垃圾","恶心","跌了","完了","危险","割"]
    neutral = ["吧","可能","感觉","应该","不知道"]
    
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


def build_summary(post_text, comments, sentiment, sentiment_detail):
    """生成评论摘要"""
    if not comments:
        return "暂无评论"
    
    # 取点赞最高的评论
    top_comments = sorted(comments, key=lambda x: x["like"], reverse=True)[:5]
    
    lines = []
    for i, c in enumerate(top_comments, 1):
        text = c["text"][:80] + ("..." if len(c["text"]) > 80 else "")
        lines.append(f"{i}. {text} (👍{c['like']})")
    
    return "\n".join(lines)


def send_feishu(msg):
    """发送飞书消息"""
    payload = {"msg_type": "text", "content": {"text": msg}}
    resp = requests.post(FEISHU_WEBHOOK, json=payload, timeout=10)
    return resp.json()


def send_feishu_card(title, sections):
    """发送飞书富文本卡片"""
    elements = [{"tag": "h1", "text": {"content": title, "tag": "plain_text"}}]
    for sec in sections:
        elements.append({"tag": "h2", "text": {"content": sec["title"], "tag": "plain_text"}})
        elements.append({"tag": "note", "elements": [{"tag": "plain_text", "content": sec["body"]}]})
    
    payload = {
        "msg_type": "interactive",
        "card": {
            "header": {"title": {"content": title, "tag": "plain_text"}, "template": "purple"},
            "elements": elements
        }
    }
    resp = requests.post(FEISHU_WEBHOOK, json=payload, timeout=10)
    return resp.json()


def load_last_ids():
    if LAST_ID_FILE.exists():
        return json.loads(LAST_ID_FILE.read_text())
    return {}


def save_last_ids(ids):
    LAST_ID_FILE.write_text(json.dumps(ids, ensure_ascii=False))


def main():
    cookie = load_cookie()
    if not cookie:
        print("错误: 未找到微博 Cookie")
        sys.exit(1)

    print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] 开始检测微博...")

    last_ids = load_last_ids()
    all_new_posts = []

    for blogger in WATCHLIST:
        uid = blogger["uid"]
        name = blogger["name"]
        
        try:
            posts = fetch_posts(uid, cookie)
        except Exception as e:
            print(f"获取微博失败 {uid}: {e}")
            continue

        if not posts:
            print(f"未获取到微博 UID={uid}")
            continue

        new_posts = []
        last_known = last_ids.get(uid)
        
        for post in posts:
            post_id = str(post.get("idstr", ""))
            if post_id == last_known:
                break
            new_posts.append(post)

        if new_posts:
            # 取最新的那个
            latest = new_posts[0]
            last_ids[uid] = str(latest.get("idstr", ""))
            all_new_posts.append((name, latest))
            print(f"  {name}: 发现 {len(new_posts)} 条新微博")

    if not all_new_posts:
        print("没有新微博")
        return

    save_last_ids(last_ids)

    # 处理每条新微博
    for name, post in all_new_posts:
        post_id = str(post.get("idstr", ""))
        post_text = clean_text(post.get("text_raw", post.get("text", "")))
        post_url = f"https://weibo.com/{uid}/{post_id}"
        
        # 过滤非股票内容
        if is_stock_related(post_text) < 1:
            print(f"  [跳过] 非股票相关内容")
            continue

        print(f"\n分析: {post_text[:50]}...")

        # 获取评论
        comments = fetch_comments(post_id, cookie, max_pages=5)
        print(f"  获取到 {len(comments)} 条评论")

        # 情绪分析
        sentiment, pos, neg, total = analyze_sentiment(comments)
        comment_summary = build_summary(post_text, comments, sentiment, None)

        # 生成推送消息
        short_text = post_text[:200] + ("..." if len(post_text) > 200 else "")
        
        msg = f"""📢 【{name}】新发微博（股票相关）

📝 内容：
{short_text}

💬 评论分析（{total}条）
情绪：{sentiment}
👥 高赞评论：
{comment_summary}

🔗 {post_url}"""

        print(f"\n发送飞书通知...")
        result = send_feishu(msg)
        print(f"  发送结果: {result.get('msg', result)}")


if __name__ == "__main__":
    main()

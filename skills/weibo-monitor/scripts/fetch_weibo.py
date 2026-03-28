#!/usr/bin/env python3
"""
Weibo Monitor - 监控指定微博博主的最新发文
用法: python3 fetch_weibo.py [uid] [limit]
"""

import json
import os
import sys
import requests
import sys
from datetime import datetime
from pathlib import Path

# 加载 cookie
COOKIE_FILE = Path(__file__).parent.parent / "config" / "cookie.env"
FEISHU_WEBHOOK_FILE = Path(__file__).parent.parent / "config" / "feishu_webhook.env"

def load_cookie():
    env_content = COOKIE_FILE.read_text()
    for line in env_content.splitlines():
        if line.startswith("WEIBO_COOKIE="):
            return line.split("=", 1)[1].strip().strip('"')
    return None

def load_feishu_webhook():
    if FEISHU_WEBHOOK_FILE.exists():
        for line in FEISHU_WEBHOOK_FILE.read_text().splitlines():
            if line.startswith("FEISHU_WEBHOOK="):
                return line.split("=", 1)[1].strip().strip('"')
    # fallback to TrendRadar's webhook
    return "https://open.feishu.cn/open-apis/bot/v2/hook/f54d31a7-226d-4fac-aeaf-44b84c5c85b7"

def fetch_weibo(uid, cookie, limit=10):
    """获取微博用户最新微博"""
    url = f"https://weibo.com/ajax/statuses/mymblog"
    params = {
        "uid": uid,
        "page": 1,
        "feature": 0,
        "lang": "zh-CN"
    }
    headers = {
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Cookie": cookie,
        "Accept": "application/json, text/plain, */*",
        "Referer": f"https://weibo.com/u/{uid}",
        "XSRF-TOKEN": cookie.split("XSRF-TOKEN=")[1].split(";")[0] if "XSRF-TOKEN=" in cookie else ""
    }
    
    resp = requests.get(url, params=params, headers=headers, timeout=10)
    resp.raise_for_status()
    data = resp.json()
    if data.get("ok") == -100:
        raise RuntimeError(f"微博 Cookie 已失效，需要重新登录: uid={uid}")
    
    posts = data.get("data", {}).get("list", [])
    user_info = data.get("data", {}).get("userInfo", {})
    
    return posts[:limit], user_info

def parse_text(post):
    """解析微博文本内容"""
    # 微博返回的文本可能在 text 或 text_raw 字段
    text = post.get("text_raw", post.get("text", ""))
    # 清理 HTML 标签
    import re
    text = re.sub(r'<[^>]+>', '', text)
    text = text.replace('&nbsp;', ' ').replace('&amp;', '&').replace('&lt;', '<').replace('&gt;', '>')
    return text.strip()

def is_stock_related(text):
    """简单判断内容是否与股票/金融市场相关"""
    keywords = [
        "股票", "A股", "大盘", "上证", "深证", "创业板", "科创板", "北证",
        "指数", "涨跌", "涨停", "跌停", "持仓", "建仓", "清仓", "加仓", "减仓",
        "牛市", "熊市", "回调", "反弹", "突破", "支撑", "压力",
        "板块", "概念", "龙头", "庄家", "主力", "资金", "量能", "缩量", "放量",
        "研报", "业绩", "财报", "PE", "PB", "估值", "股息", "分红",
        "期权", "期货", "融资", "融券", "杠杆", "做空", "做多",
        "美联储", "加息", "降息", "美股", "港股", "汇率", "人民币", "美元",
        "央行", "货币政策", "经济数据", "CPI", "PPI", "GDP",
        "宁德", "茅台", "比亚迪", "腾讯", "阿里", "美团", "京东",
        "新能源", "半导体", "芯片", "AI", "人工智能", "医药", "白酒",
        "证券", "基金", "私募", "公募", "量化", "对冲",
    ]
    text_lower = text.lower()
    return sum(1 for kw in keywords if kw in text) >= 2

def send_feishu(webhook, message):
    """发送飞书消息"""
    payload = {
        "msg_type": "text",
        "content": {"text": message}
    }
    resp = requests.post(webhook, json=payload, timeout=10)
    return resp.json()

def get_state_file():
    """获取状态文件路径（记录上次抓取的最新微博ID）"""
    return Path(__file__).parent.parent / "config" / "last_post_id.txt"

def load_last_post_id():
    """加载上次已处理的最新微博ID"""
    sf = get_state_file()
    if sf.exists():
        return sf.read_text().strip()
    return None

def save_last_post_id(post_id):
    """保存最新微博ID"""
    get_state_file().write_text(str(post_id))

def main():
    # 默认监控的微博 UID
    DEFAULT_UID = "2014433131"
    
    uid = sys.argv[1] if len(sys.argv) > 1 else DEFAULT_UID
    limit = int(sys.argv[2]) if len(sys.argv) > 2 else 10
    
    cookie = load_cookie()
    if not cookie:
        print("错误: 未找到微博 Cookie，请检查 config/cookie.env")
        sys.exit(1)
    
    print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] 开始抓取微博 UID={uid}")
    
    posts, user_info = fetch_weibo(uid, cookie, limit)
    
    if not posts:
        print("未获取到微博，可能 Cookie 已过期")
        sys.exit(1)
    
    username = user_info.get("name", user_info.get("screen_name", "未知用户"))
    print(f"博主: {username}, 获取到 {len(posts)} 条微博")
    
    # 检查是否有新微博（跳过置顶帖，避免置顶命中状态导致漏检）
    last_id = load_last_post_id()
    effective_posts = [post for post in posts if not post.get("isTop")]
    last_id_is_top = any(str(post.get("idstr", "")) == last_id and post.get("isTop") for post in posts)
    new_posts = []

    if last_id_is_top:
        print("检测到旧状态命中了置顶帖，切换为非置顶微博基线")
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
            if post_id == last_id:
                break
            new_posts.append(post)
    
    # 反转顺序（按时间正序）
    new_posts = new_posts[::-1]
    
    webhook = load_feishu_webhook()
    
    if new_posts:
        print(f"发现 {len(new_posts)} 条新微博")
        
        stock_posts = []
        for post in new_posts:
            text = parse_text(post)
            created_at = post.get("created_at", "")
            post_url = f"https://weibo.com/{uid}/{post.get('idstr', '')}"
            
            if is_stock_related(text):
                stock_posts.append((text, created_at, post_url))
        
        # 发送通知
        if stock_posts:
            msg = f"📢 【{username}】新发微博（股票相关 {len(stock_posts)} 条）\n\n"
            for i, (text, created_at, url) in enumerate(stock_posts[:5], 1):
                msg += f"{i}. {text[:100]}"
                if len(text) > 100:
                    msg += "..."
                msg += f"\n   {url}\n\n"
            
            if len(stock_posts) > 5:
                msg += f"...还有 {len(stock_posts) - 5} 条\n"
        else:
            msg = f"📢 【{username}】新发微博 {len(new_posts)} 条\n无明显股票相关内容"
        
        send_feishu(webhook, msg)
        
        # 保存最新微博ID
        save_last_post_id(str(new_posts[-1].get("idstr", "")))
        
    else:
        print("没有新微博")
    
    # 输出所有抓取的微博（调试用）
    print("\n--- 最近微博 ---")
    for post in posts[:3]:
        text = parse_text(post)
        stock_tag = "📈" if is_stock_related(text) else ""
        print(f"{stock_tag} {text[:60]}...")
    
    print("\n--- 完成 ---")

if __name__ == "__main__":
    main()

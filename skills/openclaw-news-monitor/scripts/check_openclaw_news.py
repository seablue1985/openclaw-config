#!/usr/bin/env python3
"""
OpenClaw News Monitor - 监控 OpenClaw 相关更新
- OpenClaw 版本更新
- clawhub.com 新 Skill
- GitHub AI Agent 相关热门项目
"""

import json, re, sys, requests
from datetime import datetime
from pathlib import Path

FEISHU_WEBHOOK = "https://open.feishu.cn/open-apis/bot/v2/hook/f54d31a7-226d-4fac-aeaf-44b84c5c85b7"

STATE_FILE = Path(__file__).parent.parent / "state" / "openclaw_news_state.json"
STATE_FILE.parent.mkdir(exist_ok=True)

OPENCLAW_VERSION_FILE = Path.home() / ".openclaw" / "openclaw.json"

# 关注的 GitHub 仓库（AI Agent 相关）
WATCH_REPOS = [
    {"owner": "openclaw", "repo": "openclaw", "name": "OpenClaw"},
    {"owner": "anthropics", "repo": "claude-code", "name": "Claude Code"},
    {"owner": "microsoft", "repo": "RD-Agent", "name": "RD-Agent"},
    {"owner": "seablue1985", "repo": "everything-claude-code-zh", "name": "Claude Code 中文指南"},
]

FINANCE_SKILL_KEYWORDS = ["stock", "quant", "finance", "trading", "market", "investment", "A股", "量化", "金融"]

def load_state():
    if STATE_FILE.exists():
        return json.loads(STATE_FILE.read_text())
    return {}

def save_state(state):
    STATE_FILE.write_text(json.dumps(state, ensure_ascii=False, indent=2))

def get_current_version():
    """获取当前安装的 OpenClaw 版本"""
    try:
        import subprocess
        r = subprocess.run(["openclaw", "--version"], capture_output=True, text=True, timeout=5)
        return r.stdout.strip()
    except:
        return None

def check_openclaw_update():
    """检查 OpenClaw 是否有版本更新"""
    try:
        resp = requests.get(
            "https://api.github.com/repos/openclaw/openclaw/releases/latest",
            headers={"Accept": "application/json"},
            timeout=10
        )
        data = resp.json()
        latest = data.get("tag_name", "").lstrip("v")
        current = get_current_version() or ""
        
        # 提取版本号
        latest_match = re.search(r"(\d+\.\d+\.\d+)", latest)
        current_match = re.search(r"(\d+\.\d+\.\d+)", current)
        
        if latest_match and current_match:
            latest_v = latest_match.group(1)
            current_v = current_match.group(1)
            is_new = latest_v != current_v
            return {
                "has_update": is_new,
                "latest": latest_v,
                "current": current_v,
                "url": data.get("html_url", "https://github.com/openclaw/openclaw/releases"),
                "body": data.get("body", "")[:500]
            }
    except Exception as e:
        return {"has_update": False, "error": str(e)}
    return {"has_update": False}

def check_github_trending():
    """检查 GitHub AI Agent 相关热门项目"""
    try:
        # 获取 AI Agent 相关 trending
        resp = requests.get(
            "https://api.github.com/search/repositories",
            params={
                "q": "AI agent OR autonomous agent OR AI coding in:readme",
                "sort": "stars",
                "order": "desc",
                "per_page": 5
            },
            headers={"Accept": "application/json"},
            timeout=10
        )
        data = resp.json()
        repos = []
        for item in data.get("items", [])[:5]:
            repos.append({
                "name": item["full_name"],
                "desc": item["description"] or "",
                "stars": item["stargazers_count"],
                "url": item["html_url"],
                "updated": item["updated_at"][:10]
            })
        return repos
    except Exception as e:
        return []

def check_clawhub_skills():
    """检查 clawhub.com 新 Skill（尝试多种方式）"""
    skills = []
    
    # 方式1: 直接访问 clawhub API
    try:
        resp = requests.get(
            "https://clawhub.com/api/skills?sort=recent&limit=10",
            headers={"Accept": "application/json", "User-Agent": "Mozilla/5.0"},
            timeout=10
        )
        if resp.status_code == 200:
            data = resp.json()
            for skill in data.get("skills", [])[:5]:
                skills.append({
                    "name": skill.get("name", ""),
                    "desc": skill.get("description", ""),
                    "url": f"https://clawhub.com/skills/{skill.get('slug', '')}"
                })
            return skills
    except:
        pass
    
    # 方式2: 通过 GitHub 搜索
    try:
        resp = requests.get(
            "https://api.github.com/search/code",
            params={
                "q": "openclaw skill site:clawhub.com OR site:github.com/samber",
                "per_page": 5
            },
            headers={"Accept": "application/json"},
            timeout=10
        )
        # 不太可能成功，跳过
    except:
        pass
    
    return skills

def check_openclaw_docs():
    """检查 OpenClaw 文档更新"""
    try:
        resp = requests.get(
            "https://api.github.com/repos/openclaw/openclaw/commits",
            params={"per_page": 3},
            headers={"Accept": "application/json"},
            timeout=10
        )
        commits = []
        for c in resp.json()[:3]:
            commits.append({
                "msg": c["commit"]["message"].split("\n")[0][:80],
                "date": c["commit"]["author"]["date"][:10],
                "author": c["commit"]["author"]["name"]
            })
        return commits
    except:
        return []

def send_feishu(msg):
    """发送飞书"""
    payload = {"msg_type": "text", "content": {"text": msg}}
    resp = requests.post(FEISHU_WEBHOOK, json=payload, timeout=10)
    return resp.json()

def build_report(update_info, trending, commits):
    """构建报告"""
    lines = []
    lines.append("━━━━━━━━━━━━━━━━━━━━")
    lines.append("🤖 OpenClaw 动态周报")
    lines.append(f"📅 {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    lines.append("━━━━━━━━━━━━━━━━━━━━")
    
    # 版本更新
    if update_info.get("has_update"):
        lines.append("")
        lines.append("🆕 **版本更新 available!**")
        lines.append(f"当前版本: {update_info.get('current', '?')}")
        lines.append(f"最新版本: {update_info.get('latest', '?')}")
        lines.append(f"🔗 {update_info.get('url', '')}")
    else:
        lines.append("")
        lines.append("✅ OpenClaw 已是最新版本")
        v = update_info.get("current", get_current_version() or "?")
        lines.append(f"当前版本: {v}")
    
    # GitHub 热门
    if trending:
        lines.append("")
        lines.append("🔥 GitHub AI Agent 热门项目")
        for r in trending[:5]:
            stars = f"{r['stars']:,}" if r['stars'] else "?"
            lines.append(f"  ★ {stars} | [{r['name']}]({r['url']})")
            if r['desc']:
                desc = r['desc'][:60] + ('...' if len(r['desc']) > 60 else '')
                lines.append(f"         {desc}")
    
    # 最近更新
    if commits:
        lines.append("")
        lines.append("📝 OpenClaw 最近更新")
        for c in commits[:3]:
            lines.append(f"  • {c['msg']}")
            lines.append(f"    [{c['date']} by {c['author']}]")
    
    lines.append("")
    lines.append("━━━━━━━━━━━━━━━━━━━━")
    lines.append("📊 数据来源：GitHub | {time}".format(time=datetime.now().strftime('%H:%M:%S')))
    
    return '\n'.join(lines)

def main():
    state = load_state()
    
    print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] 检查 OpenClaw 动态...")
    
    # 检查版本更新
    update_info = check_openclaw_update()
    
    # 检查 GitHub trending
    trending = check_github_trending()
    
    # 检查最近 commits
    commits = check_openclaw_docs()
    
    # 判断是否需要推送（版本更新 或 第一次运行）
    should_push = False
    push_reason = []
    
    if update_info.get("has_update"):
        should_push = True
        push_reason.append(f"版本更新: {update_info.get('current')} → {update_info.get('latest')}")
    
    # 检查 trending 是否有新的大热门
    if trending:
        top_starred = trending[0].get("stars", 0)
        last_top = state.get("last_top_stars", 0)
        if top_starred > last_top * 1.5:  # 热门项目 stars 暴涨
            should_push = True
            push_reason.append(f"新热门项目: {trending[0]['name']}")
        state["last_top_stars"] = top_starred
    
    # 第一次运行，发送初始报告
    if "initialized" not in state:
        should_push = True
        push_reason.append("初始配置完成")
        state["initialized"] = True
    
    # 构建报告
    report = build_report(update_info, trending, commits)
    
    print(f"版本: {update_info.get('current','?')} / {update_info.get('latest','?')}")
    print(f"GitHub trending: {len(trending)} 个项目")
    print(f"最近 commits: {len(commits)} 条")
    
    if should_push:
        print(f"\n推送原因: {', '.join(push_reason)}")
        result = send_feishu(report)
        print(f"发送结果: {result}")
    else:
        print("\n无新增内容，跳过推送")
    
    save_state(state)

if __name__ == "__main__":
    main()

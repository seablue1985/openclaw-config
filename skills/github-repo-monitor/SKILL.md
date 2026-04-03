# GitHub Repo Monitor Skill

自动追踪指定 GitHub 仓库的更新情况，分析 changelog 并判断是否应更新本地副本。

## 功能

| 功能 | 说明 |
|------|------|
| 🔍 上游更新检测 | 检查 upstream remote 与本地的 commit 差距 |
| 📊 优先级分类 | 按 feat/fix/refactor/breaking 打标签 |
| 🧠 智能建议 | 自动判断是否建议更新本地仓库 |
| 📲 飞书通知 | 有重要更新时推送摘要到飞书 |
| 📝 报告存档 | 输出 Markdown + JSON 状态文件 |

## 监控范围

自动发现并监控以下仓库：
- `daily_stock_analysis`（上游 ZhuLinsen）
- `qlib`（上游 seablue1985）
- 其他带 upstream remote 的 Git 仓库

## 配置

编辑 `config/repos.json` 添加/删除仓库：

```json
[
  {"path": "/path/to/repo1"},
  {"path": "/path/to/repo2"}
]
```

留空则自动发现 workspace 下所有有 upstream 的仓库。

## 使用方法

### 手动检查
```bash
/usr/local/bin/python3 /Users/ling/.openclaw/skills/github-repo-monitor/scripts/check_updates.py
```

### 定时自动
LaunchAgent 已配置，每日 09:00 / 21:00 自动检查。

```bash
# 查看日志
cat ~/Library/Logs/github-repo-monitor.log

# 重启服务
launchctl unload ~/Library/LaunchAgents/com.ling.github-repo-monitor.plist
launchctl load ~/Library/LaunchAgents/com.ling.github-repo-monitor.plist
```

## 报告示例

```
# GitHub 仓库更新报告 — 2026-03-22

**检查仓库数：8 | 建议更新：2 | 已最新：5**

## 🔔 需要关注的更新

### daily_stock_analysis ⭐⭐⭐（v3.9.0）
- 当前版本：v3.4.8
- 上游版本：v3.9.0
- 落后：20 commits | Ahead：0
- **建议：落后 20 个 commits，建议一次性合并**
- 包含：Slack通知、REPORT_LANGUAGE配置、TickFlow行情、AutoComplete

## ✅ 所有仓库已最新，无需更新
```
